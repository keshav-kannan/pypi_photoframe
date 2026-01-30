from cProfile import label
import os
import sys
import time
import json
import shutil
import random
import argparse
from dataclasses import dataclass
from typing import List, Optional, Tuple
import datetime
import pygame


# -------------------------
# Config defaults
# -------------------------
SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
STATE_FILE_NAME = ".photo_frame_state.json"
FAVORITES_DIR_NAME = "favorites"

DEFAULT_PHOTOS_WINDOWS = r"C:\PhotoFrame\photos"
DEFAULT_DATA_WINDOWS   = r"C:\PhotoFrame\data"

DEFAULT_PHOTOS_LINUX = "/home/admin/photo_frame/photos"
DEFAULT_DATA_LINUX   = "/home/admin/photo_frame/data"



text_color = (255, 255, 255) # white, black = (0, 0, 0)
text_outline = (255, 255, 255) #white, black = (0, 0, 0)

@dataclass
class Config:
    photos_dir: str
    data_dir: str
    fullscreen: bool = True
    target_fps: int = 30
    slide_seconds: float = 10.0

    # Font configuration
    font_file: str = "assets/InterVariable.ttf"   # relative to data_dir
    font_fallback_name: str = "DejaVu Sans"


    # Overlay behavior
    overlay_timeout_sec: float = 3.0

    # Folder rescanning
    rescan_interval_sec: float = 10.0

    # Gesture thresholds
    swipe_min_dx: int = 180          # pixels
    swipe_max_dt: float = 0.55       # seconds

    # UI layout
    ui_padding: int = 16
    button_height: int = 72
    button_gap: int = 12

    overlay_width_ratio: float = 0.95   # % width of screen for bottom overlay
    min_button_width: int = 110         # safety clamp
    max_button_width: int = 180

    captions_default_on: bool = True
    caption_margin_bottom: int = 24  # distance from bottom (or from overlay)
    caption_line_gap: int = 6
    caption_bg_pad_x: int = 22
    caption_bg_pad_y: int = 14
    interval_steps: tuple[float, ...] = (2.0, 3.0, 5.0, 8.0, 10.0)

    use_text_outline: bool = False   # set True later if you want outlines back
    # Captions behavior
    caption_mode_default: str = "fade"  # "off" | "on" | "fade"
    caption_visible_seconds: float = 3.0
    caption_fade_in_seconds: float = 0.25
    caption_fade_out_seconds: float = 0.60

    caption_max_width_ratio: float = 0.88   # wrap within 88% of screen width
    caption_max_lines: int = 4              # for the main caption
    folder_max_lines: int = 2               # for folder line(s)

    # Auto sizing
    caption_base_size: int = 40
    caption_min_size: int = 22
    folder_base_size: int = 22
    folder_min_size: int = 16

    caption_line_gap: int = 6
    caption_margin_bottom: int = 24

    # Auto sleep after inactivity
    auto_sleep_enabled: bool = True
    auto_sleep_seconds: float = 3600.0  # 1 hour

    # Clock styling
    clock_font_size: int = 100
    clock_alpha: int = 200          # 50% of 255 ≈ 128
    clock_color: tuple = (255, 255, 255)
    clock_margin: int = 18
    clock_format: str = "%H:%M"

    # Indicator
    indicator_padding: int = 12

    # Brightness
    brightness_steps: tuple[float, ...] = (1.0, 0.7, 0.4, 0.2)  # 100%, 70%, 40%, 20%
    brightness_default: float = 1.0
    night_brightness: float = 0.25  # effective max brightness at night

    auto_dim_enabled: bool = True
    auto_dim_start_hour: int = 20   # 8pm
    auto_dim_end_hour: int = 8      # 8am

    # Clock
    clock_enabled: bool = True
    clock_format: str = "%H:%M"
    clock_margin: int = 12

class AppFonts:
    font_file: str = "assets/Inter-Regular.ttf"   # relative to data_dir
    font_fallback_name: str = "DejaVu Sans"

class AppPaths:
    data_dir: str = ""
    font_file: str = ""
    font_fallback_name: str = ""


# -------------------------
# Utilities
# -------------------------
def now_monotonic() -> float:
    return time.monotonic()


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def safe_relpath(path: str, base: str) -> str:
    """Return relative path if under base; else basename."""
    try:
        rel = os.path.relpath(path, base)
        if rel.startswith(".."):
            return os.path.basename(path)
        return rel
    except Exception:
        return os.path.basename(path)

def load_font(size: int, *, bold: bool = False) -> pygame.font.Font:
    try:
        font_path = os.path.join(AppPaths.data_dir, AppPaths.font_file)
        if os.path.isfile(font_path):
            return pygame.font.Font(font_path, size)
    except Exception:
        pass
    return pygame.font.SysFont(AppPaths.font_fallback_name, size, bold=bold)

def compute_button_font_size(
    labels: list[str],
    button_w: int,
    button_h: int,
    padding: int = 12,
    safety_px: int = 2,
    min_size: int = 10
) -> int:
    max_w = button_w - 2 * padding - safety_px
    max_h = button_h - 2 * padding - safety_px

    # Start from a size that has a chance to fit height-wise
    size = max_h

    while size >= min_size:
        font = load_font(size)
        fits = True

        for text in labels:
            w, h = font.size(text)
            if w > max_w or h > max_h:
                fits = False
                break

        if fits:
            return size

        size -= 1

    return min_size


def worst_case_button_labels() -> list[str]:
    """
    Return the longest labels that might appear on buttons, so the chosen
    global font size always fits even when labels change at runtime.
    """
    return [
        "Prev",
        "Pause",                 # Play/Pause toggles - Pause is slightly wider in some fonts
        "Next",
        "Sleep",
        "Shuffle: Off",          # longer than "Shuffle: On"
        "Captions: FADE",        # longest of OFF/ON/FADE
        "Bright: 100%",          # longest brightness label
        "Reload",
        "Exit",
        "10s",                   # interval label
    ]

def render_text_to_fit(text: str, max_w: int, max_h: int) -> pygame.Surface:
    """
    Render text using the bundled font, shrinking until it fits inside max_w x max_h.
    """
    size = max_h  # start large
    min_size = 10

    while size >= min_size:
        font = load_font(size)
        surf = font.render(text, True, (255, 255, 255))
        if surf.get_width() <= max_w and surf.get_height() <= max_h:
            return surf
        size -= 1

    # Fallback (tiny)
    font = load_font(min_size)
    return font.render(text, True, (255, 255, 255))

def list_media_files(folder: str) -> List[str]:
    files: List[str] = []
    if not os.path.isdir(folder):
        return files

    for root, _, fnames in os.walk(folder):
        pass


        for fn in fnames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SUPPORTED_EXTS:
                files.append(os.path.join(root, fn))

    files.sort(key=lambda p: p.lower())
    return files


def file_signature(paths: List[str]) -> Tuple[int, int]:
    """A cheap signature: (count, sum of mtimes seconds)."""
    s = 0
    for p in paths:
        try:
            s += int(os.path.getmtime(p))
        except OSError:
            pass
    return (len(paths), s)


def load_state(state_path: str) -> dict:
    if not os.path.isfile(state_path):
        return {}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state_path: str, state: dict) -> None:
    tmp = state_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, state_path)
    except Exception:
        # best effort; ignore
        pass


def ensure_favorites_dir(folder: str) -> str:
    fav_dir = os.path.join(folder, FAVORITES_DIR_NAME)
    os.makedirs(fav_dir, exist_ok=True)
    return fav_dir


def is_favorited(favorites_dir: str, filepath: str) -> bool:
    if not filepath:
        return False
    base = os.path.basename(filepath)
    return os.path.isfile(os.path.join(favorites_dir, base))



def copy_to_favorites(favorites_dir: str, filepath: str) -> bool:
    try:
        os.makedirs(favorites_dir, exist_ok=True)
        dst = os.path.join(favorites_dir, os.path.basename(filepath))
        if os.path.abspath(filepath) == os.path.abspath(dst):
            return True
        if os.path.isfile(dst):
            return True
        shutil.copy2(filepath, dst)
        return True
    except Exception:
        return False


def wrap_text_to_width(font: pygame.font.Font, text: str, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width (pixels)."""
    words = text.split()
    if not words:
        return [""]

    lines = []
    current = words[0]
    for w in words[1:]:
        trial = current + " " + w
        if font.size(trial)[0] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def build_wrapped_surfaces(
    text: str,
    base_size: int,
    min_size: int,
    max_width: int,
    max_lines: int,
    *,
    uppercase: bool,
    color=(255, 255, 255),
    alpha: int = 255
) -> tuple[list[pygame.Surface], int]:
    """
    Auto-scales font size down until wrapped text fits within max_lines.
    Returns (surfaces, final_font_size).
    """
    if uppercase:
        text = text.upper()

    text = text.strip()
    if not text:
        return ([], base_size)

    size = base_size
    final_lines = []

    while size >= min_size:
        font = load_font(size)
        lines = wrap_text_to_width(font, text, max_width)

        if len(lines) <= max_lines:
            final_lines = lines
            break
        size -= 1

    # If still too many lines at min size, hard-trim
    if not final_lines:
        font = load_font(size)
        lines = wrap_text_to_width(font, text, max_width)
        final_lines = lines[:max_lines]

    font = load_font(size if size >= min_size else min_size)

    surfaces = []
    for line in final_lines:
        s = font.render(line, True, color)
        if alpha != 255:
            s.set_alpha(alpha)
        surfaces.append(s)

    return (surfaces, font.get_height())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simple Photo Frame (Pygame)")
    p.add_argument("--photos", default=None, help="Photos directory (slideshow source)")
    p.add_argument("--data", default=None, help="Data directory (state, favorites, assets)")
    p.add_argument("--windowed", action="store_true", help="Run in a window (dev mode)")
    p.add_argument("--seconds", type=float, default=10.0, help="Seconds per slide")
    p.add_argument("--rescan", type=float, default=10.0, help="Rescan folder interval seconds")
    return p.parse_args()


def sidecar_caption_txt(image_path: str) -> Optional[str]:
    """
    Looks for a .txt file matching the image path:
      photo.jpg -> photo.txt
    Returns stripped text or None.
    """
    base, _ = os.path.splitext(image_path)
    txt_path = base + ".txt"
    if not os.path.isfile(txt_path):
        return None
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        return text if text else None
    except Exception:
        return None


def folder_caption(image_path: str, photos_root: str) -> str:
    """
    Returns the immediate folder name containing the image.
    If image is directly in photos_root, returns photos_root folder name.
    """
    photos_root = os.path.abspath(photos_root)
    parent = os.path.abspath(os.path.dirname(image_path))

    # If the image is directly under the root folder
    if parent == photos_root:
        return os.path.basename(photos_root) or photos_root

    # Otherwise, return the immediate parent folder name
    name = os.path.basename(parent)
    return name or (os.path.basename(photos_root) or photos_root)


def draw_vertical_gradient_alpha(surface: pygame.Surface, rect: pygame.Rect, alpha_top: int, alpha_bottom: int) -> None:
    """
    Draw a vertical black->black gradient where only alpha changes.
    Faster than per-pixel for small heights; fine for 120-220px overlays.
    """
    h = rect.height
    if h <= 0:
        return
    for i in range(h):
        a = int(alpha_top + (alpha_bottom - alpha_top) * (i / max(1, h - 1)))
        pygame.draw.line(surface, (0, 0, 0, a),
                         (rect.left, rect.top + i), (rect.right - 1, rect.top + i))


def render_text(font: pygame.font.Font, text: str,
                color=(255, 255, 255),
                outline: bool = False,
                outline_color=(0, 0, 0),
                outline_px: int = 2) -> pygame.Surface:
    """
    Render text optionally with outline.
    """
    if not outline:
        return font.render(text, True, color)

    base = font.render(text, True, color)
    w, h = base.get_size()
    surf = pygame.Surface((w + 2 * outline_px, h + 2 * outline_px), pygame.SRCALPHA)

    for ox in range(-outline_px, outline_px + 1):
        for oy in range(-outline_px, outline_px + 1):
            if ox == 0 and oy == 0:
                continue
            surf.blit(font.render(text, True, outline_color), (ox + outline_px, oy + outline_px))

    surf.blit(base, (outline_px, outline_px))
    return surf


# -------------------------
# Slideshow order logic
# -------------------------
class OrderManager:
    """
    Supports:
    - sequential order by sorted file list, with an index
    - shuffle order with no repeats until all seen
    """
    def __init__(self, files: List[str], shuffle: bool, start_path: Optional[str] = None):
        self.files = files[:]  # canonical sorted list
        self.shuffle = shuffle

        self.seq_index = 0
        if start_path and start_path in self.files:
            self.seq_index = self.files.index(start_path)

        self.shuffle_bag: List[int] = []
        self.shuffle_pos = 0

        # If shuffle, build initial bag and align to start path if possible.
        if self.shuffle:
            self._refill_bag()
            if start_path and start_path in self.files:
                start_idx = self.files.index(start_path)
                # Rotate bag so that start_idx is first (if present)
                if start_idx in self.shuffle_bag:
                    k = self.shuffle_bag.index(start_idx)
                    self.shuffle_bag = self.shuffle_bag[k:] + self.shuffle_bag[:k]
                    self.shuffle_pos = 0

    def _refill_bag(self) -> None:
        self.shuffle_bag = list(range(len(self.files)))
        random.shuffle(self.shuffle_bag)
        self.shuffle_pos = 0

    def set_files(self, new_files: List[str], current_path: Optional[str]) -> None:
        """Update file list and attempt to keep current position."""
        self.files = new_files[:]
        # Reset indexes sensibly
        self.seq_index = 0
        if current_path and current_path in self.files:
            self.seq_index = self.files.index(current_path)

        if self.shuffle:
            # Rebuild shuffle bag from scratch; try to start at current file
            self._refill_bag()
            if current_path and current_path in self.files:
                start_idx = self.files.index(current_path)
                if start_idx in self.shuffle_bag:
                    k = self.shuffle_bag.index(start_idx)
                    self.shuffle_bag = self.shuffle_bag[k:] + self.shuffle_bag[:k]
                    self.shuffle_pos = 0

    def toggle_shuffle(self, current_path: Optional[str]) -> None:
        self.shuffle = not self.shuffle
        if self.shuffle:
            self._refill_bag()
            if current_path and current_path in self.files:
                start_idx = self.files.index(current_path)
                if start_idx in self.shuffle_bag:
                    k = self.shuffle_bag.index(start_idx)
                    self.shuffle_bag = self.shuffle_bag[k:] + self.shuffle_bag[:k]
                    self.shuffle_pos = 0
        else:
            # If leaving shuffle, set seq index to current file if possible
            if current_path and current_path in self.files:
                self.seq_index = self.files.index(current_path)

    def reset_cycle(self, start_path: Optional[str] = None) -> None:
        """Start a fresh cycle (reshuffle bag or reset sequential index)."""
        if not self.files:
            return

        if self.shuffle:
            self._refill_bag()
            if start_path and start_path in self.files:
                start_idx = self.files.index(start_path)
                if start_idx in self.shuffle_bag:
                    k = self.shuffle_bag.index(start_idx)
                    self.shuffle_bag = self.shuffle_bag[k:] + self.shuffle_bag[:k]
                    self.shuffle_pos = 0
        else:
            self.seq_index = 0
            if start_path and start_path in self.files:
                self.seq_index = self.files.index(start_path)


    def current(self) -> Optional[str]:
        if not self.files:
            return None
        if self.shuffle:
            idx = self.shuffle_bag[self.shuffle_pos]
            return self.files[idx]
        return self.files[self.seq_index]

    def next(self) -> Optional[str]:
        if not self.files:
            return None
        if self.shuffle:
            self.shuffle_pos += 1
            if self.shuffle_pos >= len(self.shuffle_bag):
                self._refill_bag()
            return self.current()
        self.seq_index = (self.seq_index + 1) % len(self.files)
        return self.current()

    def prev(self) -> Optional[str]:
        if not self.files:
            return None
        if self.shuffle:
            self.shuffle_pos -= 1
            if self.shuffle_pos < 0:
                # If user goes "back" past start, refill and jump to last
                self._refill_bag()
                self.shuffle_pos = len(self.shuffle_bag) - 1
            return self.current()
        self.seq_index = (self.seq_index - 1) % len(self.files)
        return self.current()

    def position_text(self) -> str:
        if not self.files:
            return "0/0"
        if self.shuffle:
            # Show position inside current shuffle cycle
            return f"{self.shuffle_pos + 1}/{len(self.shuffle_bag)}"
        return f"{self.seq_index + 1}/{len(self.files)}"


# -------------------------
# UI Buttons
# -------------------------
@dataclass
class Button:
    label: str
    rect: pygame.Rect
    action: str


def make_buttons(screen_w: int, screen_h: int, cfg: Config) -> List[Button]:
    """
    Bottom bar layout constrained to cfg.overlay_width_ratio of screen.
    [Prev] [Play/Pause] [Next] [Sleep] [Shuffle] [Fav] [Reload] [Exit]
    """
    labels_actions = [
        ("Prev", "prev"),
        ("Play/Pause", "toggle_pause"),
        ("Next", "next"),
        ("Interval", "toggle_interval"),
        ("Fav", "favorite"),
        ("Captions", "toggle_captions"),
        ("Brightness", "toggle_brightness"),
        ("Shuffle", "toggle_shuffle"),
        ("Reload", "reload_reset"),
        ("Sleep", "sleep"),
        #("Exit", "exit"),
    ]

    n = len(labels_actions)
    overlay_w = int(screen_w * cfg.overlay_width_ratio)

    # Compute button width to fit inside overlay_w
    total_gaps = (n - 1) * cfg.button_gap
    raw_w = (overlay_w - total_gaps) // n
    btn_w = clamp(raw_w, cfg.min_button_width, cfg.max_button_width)

    # If clamped width causes overflow, shrink further (guaranteed fit)
    needed_w = n * btn_w + total_gaps
    if needed_w > overlay_w:
        btn_w = max(cfg.min_button_width, (overlay_w - total_gaps) // n)

    total_w = n * btn_w + total_gaps
    start_x = (screen_w - total_w) // 2
    overlay_h = cfg.button_height + cfg.ui_padding * 2
    y = screen_h - overlay_h + cfg.ui_padding


    buttons: List[Button] = []
    x = start_x
    for label, action in labels_actions:
        rect = pygame.Rect(x, y, btn_w, cfg.button_height)
        buttons.append(Button(label=label, rect=rect, action=action))
        x += btn_w + cfg.button_gap

    return buttons




# -------------------------
# Image Cache (single current image)
# -------------------------
class ImageCache:
    def __init__(self):
        self.path: Optional[str] = None
        self.surface: Optional[pygame.Surface] = None

    def load(self, path: str) -> Optional[pygame.Surface]:
        if self.path == path and self.surface is not None:
            return self.surface
        try:
            img = pygame.image.load(path)
            # Convert to display format for faster blitting
            if img.get_alpha() is not None:
                img = img.convert_alpha()
            else:
                img = img.convert()
            self.path = path
            self.surface = img
            return img
        except Exception:
            self.path = None
            self.surface = None
            return None

    def load_for_display(self, path: str, target_size: tuple[int, int]) -> pygame.Surface | None:
        key = (path, target_size)

        if not hasattr(self, "_display_cache"):
            self._display_cache = {}

        cached = self._display_cache.get(key)
        if cached is not None:
            return cached

        base = self.load(path)
        if base is None:
            return None

        try:
            surf = base
            if surf.get_size() != target_size:
                surf = pygame.transform.scale(surf, target_size)

            self._display_cache[key] = surf
            return surf
        except Exception:
            return None



def blit_centered_scaled(screen: pygame.Surface, img: pygame.Surface) -> None:
    sw, sh = screen.get_size()
    iw, ih = img.get_size()

    # If exact match, just blit
    if (iw, ih) == (sw, sh):
        screen.blit(img, (0, 0))
        return

    # Scale to fit (keep aspect)
    scale = min(sw / iw, sh / ih)
    nw = max(1, int(iw * scale))
    nh = max(1, int(ih * scale))
    scaled = pygame.transform.smoothscale(img, (nw, nh))

    x = (sw - nw) // 2
    y = (sh - nh) // 2
    screen.blit(scaled, (x, y))


# -------------------------
# Main App
# -------------------------
class PhotoFrameApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        AppFonts.font_file = self.cfg.font_file
        AppFonts.font_fallback_name = self.cfg.font_fallback_name
        self.photos_dir = os.path.abspath(cfg.photos_dir)
        self.data_dir = os.path.abspath(cfg.data_dir)
        self.button_font_size = None
        os.makedirs(self.data_dir, exist_ok=True)

        self.state_path = os.path.join(self.data_dir, STATE_FILE_NAME)
        self.favorites_dir = os.path.join(self.data_dir, FAVORITES_DIR_NAME)
        os.makedirs(self.favorites_dir, exist_ok=True)
        self.caption_cache = {}  # path -> (sidecar_text_or_none, folder_name)

        AppPaths.data_dir = self.data_dir
        AppPaths.font_file = self.cfg.font_file
        AppPaths.font_fallback_name = self.cfg.font_fallback_name

        # Runtime state
        self.running = True
        self.sleeping = False
        self.paused = False
        self.overlay_visible = False
        self.overlay_last_interaction = 0.0
        self.caption_mode = self.cfg.caption_mode_default  # "off" | "on" | "fade"
        self.image_shown_t = now_monotonic()
        self.last_drawn_path = None

        self.touch_start = None
        self.touch_start_time = 0

        self.last_touch_t = now_monotonic()

        #caching
        self._cached_img_path = None
        self._cached_img_surf = None
        self._cached_img_rect = None

        # --- Caption render cache (performance) ---
        self._cap_cache_path: str | None = None
        self._cap_cache_max_w: int | None = None
        self._cap_cache_overlay_h: int | None = None

        self._cap_cache_surfs: list[pygame.Surface] = []
        self._cap_cache_heights: list[int] = []

        # --- Indicator cache ---
        self._indicator_last_text: str | None = None
        self._indicator_surf: pygame.Surface | None = None

        # Slide timing
        self.last_advance_t = now_monotonic()

        # Folder scan
        self.files: List[str] = []
        self.files_sig = (0, 0)
        self.last_rescan_t = 0.0

                # --- Overlay bar cache ---
        self._overlay_bar_surf: pygame.Surface | None = None
        self._overlay_bar_size: tuple[int, int] | None = None

        # --- Button label cache ---
        self._button_label_cache: dict[str, pygame.Surface] = {}
        self._button_label_font_size: int | None = None


        # Input gesture tracking
        self.pointer_down = False
        self.down_pos = (0, 0)
        self.down_time = 0.0
        self.moved = False

        # Display / fonts
        self.screen: Optional[pygame.Surface] = None
        self.font: Optional[pygame.font.Font] = None
        self.font_small: Optional[pygame.font.Font] = None

        # Brightness
        self.user_brightness = float(self.cfg.brightness_default)
        self._last_effective_brightness = None  # cache to avoid reapplying constantly
        #self._xrandr_output = None              # for Pi/X11 hardware brightness (optional)

        # Order manager & image cache
        self.order: Optional[OrderManager] = None
        self.cache = ImageCache()

        # Load persisted state (best effort)
        self.persisted = load_state(self.state_path)

    def init_pygame(self) -> None:
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

        pygame.init()
        if os.name == "nt":
            pygame.mouse.set_visible(True)
        else:
            pygame.mouse.set_visible(False)  # kiosk


        pygame.font.init()
        if hasattr(self.cache, "_display_cache"):
            self.cache._display_cache.clear()

        flags = pygame.SCALED



        TARGET_W, TARGET_H = 1920, 1200
        self.logical_size = (TARGET_W, TARGET_H)

        if os.name == "nt":
            # Dev window (resizable), no SCALED
            self.screen = pygame.display.set_mode((1920, 1200), pygame.RESIZABLE)
            self.canvas = pygame.Surface(self.logical_size).convert()
        else:
            # Pi kiosk: true 1920x1200 fullscreen
            flags = pygame.FULLSCREEN
            self.screen = pygame.display.set_mode(self.logical_size, flags)
            self.canvas = self.screen  # draw directly (no extra scaling cost)


        # Force focus on Windows
        if os.name == "nt":
            pygame.event.pump()
            pygame.display.flip()


        self.font = load_font(28)
        self.font_small = load_font(20)
        pygame.mouse.set_visible(os.name == "nt")

    def map_pointer_pos(self, pos: tuple[int, int]) -> tuple[int, int]:
        if os.name != "nt":
            return pos
        wx, wy = self.screen.get_size()           # window size
        lx, ly = self.logical_size                # 1920x1200
        return (int(pos[0] * lx / wx), int(pos[1] * ly / wy))



    def rebuild_captions_cache(self, image_path: str) -> None:
        assert self.screen

        cap, fld = self.get_captions_for(image_path)

        sw, sh = self.screen.get_size()
        max_w = int(sw * self.cfg.caption_max_width_ratio)

        overlay_h = (self.cfg.button_height + self.cfg.ui_padding * 2) if self.overlay_visible else 0

        # Build at full opacity (255) ONCE
        caption_surfs: list[pygame.Surface] = []
        folder_surfs: list[pygame.Surface] = []

        if cap:
            caption_surfs, _ = build_wrapped_surfaces(
                cap,
                base_size=self.cfg.caption_base_size,
                min_size=self.cfg.caption_min_size,
                max_width=max_w,
                max_lines=self.cfg.caption_max_lines,
                uppercase=False,
                alpha=255
            )
            folder_surfs, _ = build_wrapped_surfaces(
                fld,
                base_size=self.cfg.folder_base_size,
                min_size=self.cfg.folder_min_size,
                max_width=max_w,
                max_lines=self.cfg.folder_max_lines,
                uppercase=True,
                alpha=255
            )
            lines = caption_surfs + folder_surfs
        else:
            folder_surfs, _ = build_wrapped_surfaces(
                fld,
                base_size=self.cfg.caption_base_size,
                min_size=self.cfg.caption_min_size,
                max_width=max_w,
                max_lines=self.cfg.caption_max_lines,
                uppercase=True,
                alpha=255
            )
            lines = folder_surfs

        self._cap_cache_path = image_path
        self._cap_cache_max_w = max_w
        self._cap_cache_overlay_h = overlay_h

        self._cap_cache_surfs = lines
        self._cap_cache_heights = [s.get_height() for s in lines]

    def _get_button_text_surface(self, label: str) -> pygame.Surface:
        # If font size changes, clear cache
        if self._button_label_font_size != self.button_font_size:
            self._button_label_cache.clear()
            self._button_label_font_size = self.button_font_size

        surf = self._button_label_cache.get(label)
        if surf is not None:
            return surf

        font = load_font(self.button_font_size)
        # Keep it alpha-safe; pygame font surfaces are fine
        surf = font.render(label, True, (255, 255, 255))
        self._button_label_cache[label] = surf
        return surf

    def get_current_image_surface(self, path: str):
        if path == self._cached_img_path and self._cached_img_surf is not None:
            return self._cached_img_surf

        surf = pygame.image.load(path)
        # convert to display format (much faster blits)
        surf = surf.convert()

        # If already 1920x1200, do NOT scale
        sw, sh = self.screen.get_size()
        if surf.get_width() != sw or surf.get_height() != sh:
            # scale (fast) not smoothscale
            surf = pygame.transform.scale(surf, (sw, sh))

        self._cached_img_path = path
        self._cached_img_surf = surf
        return surf

    def on_touch_down(self, pos):
        self.touch_start = pos
        self.touch_start_time = time.monotonic()
        self.wake_from_sleep()
        self.show_overlay()

    def on_touch_up(self, pos):
        if not self.touch_start:
            return

        dx = pos[0] - self.touch_start[0]
        dy = pos[1] - self.touch_start[1]
        dt = time.monotonic() - self.touch_start_time

        SWIPE_DIST = 80      # pixels
        SWIPE_TIME = 0.6     # seconds

        if abs(dx) > SWIPE_DIST and abs(dx) > abs(dy) and dt < SWIPE_TIME:
            if dx > 0:
                self.action_prev()
            else:
                self.action_next()
        else:
            # short tap
            self.handle_tap(pos)

        self.touch_start = None

    def on_touch_drag(self, pos, rel):
        pass  # optional, swipe handled on release

    def action_toggle_interval(self) -> None:
        steps = list(self.cfg.interval_steps)
        cur = float(self.cfg.slide_seconds)

        # Find next step (if current isn't exactly in list, pick the closest and advance)
        if cur in steps:
            i = steps.index(cur)
            nxt = steps[(i + 1) % len(steps)]
        else:
            # choose closest step then advance
            closest_i = min(range(len(steps)), key=lambda i: abs(steps[i] - cur))
            nxt = steps[(closest_i + 1) % len(steps)]

        self.cfg.slide_seconds = float(nxt)
        self.last_advance_t = now_monotonic()  # restart timer so it feels immediate/consistent
        self.persist_state()

    def maybe_auto_sleep(self) -> None:
        if not self.cfg.auto_sleep_enabled:
            return
        if self.sleeping:
            return
        if (now_monotonic() - self.last_touch_t) >= self.cfg.auto_sleep_seconds:
            self.go_to_sleep()


    def draw_dim_overlay(self) -> None:
        """
        Software dim: draw a translucent black layer over the image.
        Works on Windows and Pi regardless of xrandr support.
        """
        assert self.screen
        b = self.effective_brightness()
        if b >= 0.999:
            return
        alpha = int(255 * (1.0 - b))  # 0..255
        dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, alpha))
        self.screen.blit(dim, (0, 0))

    def draw_clock(self) -> None:
        if not self.cfg.clock_enabled:
            return
        if self.caption_mode == "off":
            return

        # In FADE mode, match caption fade; in ON mode, always show
        a = self.caption_alpha()
        if a <= 0:
            return

        assert self.screen
        sw, _ = self.screen.get_size()

        # Build a font at the configured size
        clock_font = load_font(self.cfg.clock_font_size)

        text = datetime.datetime.now().strftime(self.cfg.clock_format)
        surf = clock_font.render(text, True, self.cfg.clock_color)

        # Make it 50% transparent baseline, and also respect fade if enabled
        alpha = int(self.cfg.clock_alpha * (a / 255))
        surf.set_alpha(alpha)

        x = sw - surf.get_width() - self.cfg.clock_margin
        y = self.cfg.clock_margin
        self.screen.blit(surf, (x, y))

    def is_night_time(self) -> bool:
        if not self.cfg.auto_dim_enabled:
            return False
        now = datetime.datetime.now().time()
        start = datetime.time(self.cfg.auto_dim_start_hour, 0)
        end = datetime.time(self.cfg.auto_dim_end_hour, 0)
        # window crosses midnight (20:00 -> 08:00)
        return (now >= start) or (now < end)


    def effective_brightness(self) -> float:
        b = float(self.user_brightness)
        if self.is_night_time():
            b = min(b, float(self.cfg.night_brightness))
        return max(0.05, min(1.0, b))


    def cycle_brightness(self) -> None:
        steps = list(self.cfg.brightness_steps)
        cur = float(self.user_brightness)

        if cur in steps:
            i = steps.index(cur)
            nxt = steps[(i + 1) % len(steps)]
        else:
            # choose closest then advance
            closest_i = min(range(len(steps)), key=lambda i: abs(steps[i] - cur))
            nxt = steps[(closest_i + 1) % len(steps)]

        self.user_brightness = float(nxt)
        self.persist_state()

    def apply_brightness(self) -> None:
        # Software dim is applied during draw; nothing to do here.
        return

    def get_captions_for(self, image_path: str) -> Tuple[Optional[str], str]:
        if image_path in self.caption_cache:
            return self.caption_cache[image_path]

        cap = sidecar_caption_txt(image_path)          # still looks for photo.txt next to photo.jpg
        fld = folder_caption(image_path, self.photos_dir)

        self.caption_cache[image_path] = (cap, fld)
        return cap, fld

    def mark_caption_trigger(self) -> None:
        """Restart caption fade timing (used in FADE mode)."""
        self.image_shown_t = now_monotonic()

    def load_files_and_order(self) -> None:
        self.files = list_media_files(self.photos_dir)
        self.files_sig = file_signature(self.files)

        # Determine start conditions from state
        shuffle = bool(self.persisted.get("shuffle", False))
        self.paused = bool(self.persisted.get("paused", False))
        self.sleeping = bool(self.persisted.get("sleeping", False))
        self.captions_on = bool(self.persisted.get("captions_on", self.cfg.captions_default_on))

        saved_interval = self.persisted.get("slide_seconds")
        if isinstance(saved_interval, (int, float)):
            self.cfg.slide_seconds = float(saved_interval)

        saved_brightness = self.persisted.get("user_brightness")
        if isinstance(saved_brightness, (int, float)):
            self.user_brightness = float(saved_brightness)
        else:
            self.user_brightness = float(self.cfg.brightness_default)

        last_path = self.persisted.get("current_path")
        if last_path and isinstance(last_path, str):
            # stored as absolute in previous run; ensure it still exists in list
            if last_path not in self.files:
                last_path = None
        self.caption_mode = str(self.persisted.get("caption_mode", self.cfg.caption_mode_default)).lower()
        if self.caption_mode not in ("off", "on", "fade"):
            self.caption_mode = self.cfg.caption_mode_default


        self.order = OrderManager(self.files, shuffle=shuffle, start_path=last_path)

    def action_reload_reset(self) -> None:
        """Reload folder file list, and start a fresh cycle (allow repeats again)."""
        current = self.order.current() if self.order else None

        self.files = list_media_files(self.photos_dir)
        self.files_sig = file_signature(self.files)

        if hasattr(self.cache, "_display_cache"):
            self.cache._display_cache.clear()

        if self.order:
            self.order.set_files(self.files, current_path=current)
            # Fresh cycle: this is what allows repeats again immediately
            self.order.reset_cycle(start_path=current)
        self.mark_caption_trigger()
        self.caption_cache.clear()
        self.last_advance_t = now_monotonic()
        self.show_overlay()
        self.persist_state()


    def rescan_if_needed(self) -> None:
        t = now_monotonic()
        if (t - self.last_rescan_t) < self.cfg.rescan_interval_sec:
            return
        self.last_rescan_t = t

        new_files = list_media_files(self.photos_dir)
        new_sig = file_signature(new_files)
        if new_sig == self.files_sig:
            return

        self.caption_cache.clear()
        current = self.order.current() if self.order else None
        self.files = new_files
        self.files_sig = new_sig
        if self.order:
            self.order.set_files(self.files, current_path=current)

        # If folder became empty, wake overlay to show message
        self.show_overlay()

    def show_overlay(self) -> None:
        self.overlay_visible = True
        self.overlay_last_interaction = now_monotonic()
        pygame.mouse.set_visible(True)

    def hide_overlay_if_timed_out(self) -> None:
        if not self.overlay_visible:
            return
        if (now_monotonic() - self.overlay_last_interaction) > self.cfg.overlay_timeout_sec:
            self.overlay_visible = False
            pygame.mouse.set_visible(False)

    def wake_from_sleep(self) -> None:
        self.sleeping = False
        self.last_touch_t = now_monotonic()
        # After waking: do NOT immediately show overlay (matches your “one tap wake, another tap UI”)
        self.overlay_visible = False
        pygame.mouse.set_visible(False)
        self.last_advance_t = now_monotonic()
        self.mark_caption_trigger()
        self.persist_state()

    def go_to_sleep(self) -> None:
        self.sleeping = True
        self.overlay_visible = False
        pygame.mouse.set_visible(False)
        self.persist_state()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.last_advance_t = now_monotonic()
        self.persist_state()

    def persist_state(self) -> None:
        if not self.order:
            return
        state = {
            "shuffle": bool(self.order.shuffle),
            "paused": bool(self.paused),
            "sleeping": bool(self.sleeping),
            "current_path": self.order.current(),
            "saved_at_epoch": int(time.time()),
            "captions_on": bool(self.captions_on),
            "caption_mode": self.caption_mode,
            "slide_seconds": float(self.cfg.slide_seconds),
            "user_brightness": float(self.user_brightness),
        }
        save_state(self.state_path, state)

    def action_prev(self) -> None:
        if not self.order:
            return
        self.order.prev()
        self.last_advance_t = now_monotonic()
        self.mark_caption_trigger()
        self.persist_state()

    def action_next(self) -> None:
        if not self.order:
            return
        self.order.next()
        self.last_advance_t = now_monotonic()
        self.mark_caption_trigger()
        if self.screen and self.captions_on:
            cur = self.order.current()
            if cur:
                self.rebuild_captions_cache(cur)
        # If you have a caption cache builder, call it here:
        # self.rebuild_caption_cache(self.order.current())

        self.persist_state()


    def action_toggle_shuffle(self) -> None:
        if not self.order:
            return
        current = self.order.current()
        self.order.toggle_shuffle(current_path=current)
        self.persist_state()

    def action_favorite(self) -> None:
        if not self.order:
            return
        current = self.order.current()
        if current:
            copy_to_favorites(self.favorites_dir, current)
        # show overlay feedback and persist
        self.persist_state()

    def do_action(self, action: str) -> None:
        # Any UI interaction should extend overlay visibility
        self.overlay_last_interaction = now_monotonic()

        if action == "prev":
            self.action_prev()
        elif action == "next":
            self.action_next()
        elif action == "toggle_pause":
            self.toggle_pause()
        elif action == "sleep":
            self.go_to_sleep()
        elif action == "toggle_shuffle":
            self.action_toggle_shuffle()
        elif action == "toggle_captions":
            if self.caption_mode == "off":
                self.caption_mode = "on"
            elif self.caption_mode == "on":
                self.caption_mode = "fade"
                self.mark_caption_trigger()  # start fade immediately when switching to FADE
            else:
                self.caption_mode = "off"
            self.persist_state()
        elif action == "favorite":
            self.action_favorite()
        elif action == "reload_reset":
            self.action_reload_reset()
        elif action == "toggle_interval":
            self.action_toggle_interval()
        elif action == "toggle_brightness":
            self.cycle_brightness()
            self.apply_brightness()  # apply immediately
        #elif action == "exit":
            #self.running = False

    def handle_pointer_down(self, pos: Tuple[int, int]) -> None:
        self.last_touch_t = now_monotonic()
        self.pointer_down = True
        self.down_pos = pos
        self.down_time = now_monotonic()
        self.moved = False

    def handle_pointer_motion(self, pos: Tuple[int, int], rel=(0, 0)) -> None:
        if not self.pointer_down:
            return
        dx = pos[0] - self.down_pos[0]
        dy = pos[1] - self.down_pos[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self.moved = True


    def handle_pointer_up(self, pos: Tuple[int, int], buttons: List[Button]) -> None:

        if not self.pointer_down:
            return
        self.pointer_down = False

        up_time = now_monotonic()
        dt = up_time - self.down_time
        dx = pos[0] - self.down_pos[0]
        dy = pos[1] - self.down_pos[1]

        # If sleeping: any tap wakes (ignore swipe)
        if self.sleeping:
            self.wake_from_sleep()
            return

        # Swipe detection (horizontal)
        if dt <= self.cfg.swipe_max_dt and abs(dx) >= self.cfg.swipe_min_dx and abs(dx) > abs(dy):
            if dx < 0:
                self.action_next()  # swipe left -> next
            else:
                self.action_prev()  # swipe right -> prev
            self.show_overlay()
            return

        # Treat as a tap/click
        if not self.overlay_visible:
            if self.caption_mode == "fade":
                self.mark_caption_trigger()
            self.show_overlay()
            return
        # If finger moved meaningfully, do not treat as a button tap
        if self.moved:
            self.overlay_last_interaction = now_monotonic()
            return

        # If overlay is visible, check buttons
        for b in buttons:
            if b.rect.collidepoint(pos):
                self.do_action(b.action)
                return

        # Tap outside buttons: hide overlay (optional). I’m leaving it visible but refreshed.
        self.overlay_last_interaction = now_monotonic()

    def maybe_auto_advance(self) -> None:
        if self.sleeping or self.paused or not self.order:
            return
        t = now_monotonic()
        if (t - self.last_advance_t) >= self.cfg.slide_seconds:
            self.order.next()
            self.mark_caption_trigger()
            if self.screen and self.captions_on:
                cur = self.order.current()
                if cur:
                    self.rebuild_captions_cache(cur)

            # If you have a caption cache builder, call it here:
            # self.rebuild_caption_cache(self.order.current())

            self.last_advance_t = t
            self.persist_state()

    def _ensure_overlay_bar(self, sw: int, overlay_h: int) -> None:
        size = (sw, overlay_h)
        if self._overlay_bar_surf is None or self._overlay_bar_size != size:
            bar = pygame.Surface(size, pygame.SRCALPHA)
            bar.fill((0, 0, 0, 140))
            self._overlay_bar_surf = bar
            self._overlay_bar_size = size


    def draw_indicator(self) -> None:
        assert self.screen and self.font_small and self.order

        a = self.caption_alpha()
        if a <= 0:
            return

        pos = self.order.position_text()  # "1/13"
        if pos != self._indicator_last_text or self._indicator_surf is None:
            # render once
            self._indicator_last_text = pos
            # IMPORTANT: don't convert() this; keep alpha
            self._indicator_surf = self.font_small.render(pos, True, (255, 255, 255))

        surf = self._indicator_surf
        if surf is None:
            return

        # Always set alpha (avoid set_alpha(None) issues)
        surf.set_alpha(a)

        self.screen.blit(surf, (12, 12))



    def caption_alpha(self) -> int:
        """
        Returns alpha 0..255 based on mode and time since image was shown.
        - off: 0
        - on: 255
        - fade: fade in -> hold -> fade out after cfg.caption_visible_seconds
        """
        if self.caption_mode == "off":
            return 0
        if self.caption_mode == "on":
            return 255

        # fade mode
        t = now_monotonic() - self.image_shown_t
        fi = self.cfg.caption_fade_in_seconds
        hold = self.cfg.caption_visible_seconds
        fo = self.cfg.caption_fade_out_seconds

        # Fade in
        if t < fi:
            return int(255 * (t / max(fi, 1e-6)))

        # Hold visible
        if t < hold:
            return 255

        # Fade out
        t2 = t - hold
        if t2 < fo:
            return int(255 * (1.0 - (t2 / max(fo, 1e-6))))

        return 0


    def draw_overlay(self, buttons: List[Button]) -> None:
        assert self.screen and self.font
        sw, sh = self.screen.get_size()

        overlay_h = self.cfg.button_height + self.cfg.ui_padding * 2

        # Reuse bar surface (no per-frame allocation)
        self._ensure_overlay_bar(sw, overlay_h)
        if self._overlay_bar_surf is not None:
            self.screen.blit(self._overlay_bar_surf, (0, sh - overlay_h))

        # Draw buttons
        for b in buttons:
            pygame.draw.rect(self.screen, (30, 30, 30), b.rect, border_radius=12)
            pygame.draw.rect(self.screen, (200, 200, 200), b.rect, width=2, border_radius=12)

            # Dynamic labels
            label = b.label
            if b.action == "toggle_pause":
                label = "Play" if self.paused else "Pause"
            elif b.action == "toggle_shuffle" and self.order:
                label = "Shuffle: On" if self.order.shuffle else "Shuffle: Off"
            elif b.action == "toggle_captions":
                label = f"Captions: {self.caption_mode.upper()}"
            elif b.action == "toggle_interval":
                label = f"{int(self.cfg.slide_seconds)}s"
            elif b.action == "toggle_brightness":
                pct = int(self.user_brightness * 100)
                label = f"Bright: {pct}%"

            txt = self._get_button_text_surface(label)
            tx = b.rect.centerx - txt.get_width() // 2
            ty = b.rect.centery - txt.get_height() // 2
            self.screen.blit(txt, (tx, ty))




    def draw_frame(self) -> None:
        assert self.screen and self.order

        if self.sleeping:
            # Pure black screen
            self.screen.fill((0, 0, 0))
            return

        current = self.order.current()
        if not current:
            # No images
            self.screen.fill((0, 0, 0))
            assert self.font
            msg = self.font.render("No images found in folder.", True, (255, 255, 255))
            self.screen.blit(msg, (30, 30))
            return

        # Load a display-ready (converted+scaled) surface ONCE per image
        target_size = self.screen.get_size()
        img = self.cache.load_for_display(current, target_size)
        if img is None:
            self.screen.fill((0, 0, 0))
            assert self.font
            msg = self.font.render("Failed to load image. Skipping…", True, (255, 200, 200))
            self.screen.blit(msg, (30, 30))

            # Skip it next tick (do minimal work in draw)
            self.order.next()
            self.last_advance_t = now_monotonic()
            self.mark_caption_trigger()
            self.persist_state()
            return

        # Full-screen blit (fast)
        self.screen.blit(img, (0, 0))

        self.draw_dim_overlay()
        self.draw_clock()

        # If you want indicator tied to captions toggle, do this:
        if self.captions_on:
            self.draw_indicator()
            self.draw_captions(current)
        else:
            # If you truly want indicator always, keep your old behavior:
            # self.draw_indicator()
            pass


    def draw_captions(self, image_path: str) -> None:
        assert self.screen

        a = self.caption_alpha()
        if a <= 0:
            return

        sw, sh = self.screen.get_size()
        max_w = int(sw * self.cfg.caption_max_width_ratio)
        overlay_h = (self.cfg.button_height + self.cfg.ui_padding * 2) if self.overlay_visible else 0

        # Rebuild cache only when needed
        if (
            self._cap_cache_path != image_path
            or self._cap_cache_max_w != max_w
            or self._cap_cache_overlay_h != overlay_h
        ):
            self.rebuild_captions_cache(image_path)

        lines = self._cap_cache_surfs
        heights = self._cap_cache_heights
        if not lines:
            return

        bottom_margin = self.cfg.caption_margin_bottom + overlay_h
        total_h = sum(heights) + self.cfg.caption_line_gap * (len(lines) - 1)
        y = sh - bottom_margin - total_h - 8

        # Apply alpha cheaply at blit-time
        for surf in lines:
            surf.set_alpha(a)   # always set; never set_alpha(None)
            x = (sw - surf.get_width()) // 2
            self.screen.blit(surf, (x, y))
            y += surf.get_height() + self.cfg.caption_line_gap



    def run(self) -> None:
        self.init_pygame()
        self.load_files_and_order()
        assert self.screen

        clock = pygame.time.Clock()
        TARGET_FPS = 20  # good for Pi 1; try 20–30
        sw, sh = self.screen.get_size()
        overlay_h = self.cfg.button_height + self.cfg.ui_padding * 2
        y = sh - overlay_h + self.cfg.ui_padding

        buttons = make_buttons(sw, sh, self.cfg)


        # Compute once using worst-case labels so dynamic labels never overflow
        labels = worst_case_button_labels()
        self.button_font_size = compute_button_font_size(
            labels,
            buttons[0].rect.width,
            buttons[0].rect.height,
            padding=12,
            safety_px=2,
            min_size=12
        )



        # Main loop
        while self.running:
            self.rescan_if_needed()
            self.maybe_auto_sleep()
            self.maybe_auto_advance()
            self.hide_overlay_if_timed_out()
            pygame.event.pump()

            # Events
            for event in pygame.event.get():
                #print("EVENT:", pygame.event.event_name(event.type))

                #if os.name == "nt" and event.type == pygame.MOUSEBUTTONDOWN:
                    #print("CLICK:", event.pos)

                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    # Useful while developing on PC
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_SPACE:
                        self.toggle_pause()
                        self.show_overlay()
                    elif event.key == pygame.K_RIGHT:
                        self.action_next()
                        self.show_overlay()
                    elif event.key == pygame.K_LEFT:
                        self.action_prev()
                        self.show_overlay()
                    elif event.key == pygame.K_s:
                        if self.sleeping:
                            self.wake_from_sleep()
                        else:
                            self.go_to_sleep()
                    elif event.key == pygame.K_r:
                        # manual rescan
                        self.files = list_media_files(self.photos_dir)
                        self.files_sig = file_signature(self.files)
                        cur = self.order.current() if self.order else None
                        if self.order:
                            self.order.set_files(self.files, current_path=cur)
                        self.show_overlay()
                    elif event.key == pygame.K_f:
                        self.action_favorite()
                        self.show_overlay()
                    elif event.key == pygame.K_h:
                        # toggle shuffle
                        self.action_toggle_shuffle()
                        self.show_overlay()
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    #print("DOWN event:", event.pos, "sleeping:", self.sleeping, "overlay_visible:", self.overlay_visible)
                    p = self.map_pointer_pos(event.pos)
                    self.handle_pointer_down(p)
                elif event.type == pygame.MOUSEMOTION:
                    left_down = bool(getattr(event, "buttons", (0,0,0))[0]) or pygame.mouse.get_pressed(3)[0]
                    if left_down:
                        p = self.map_pointer_pos(event.pos)
                        rel = getattr(event, "rel", (0, 0))
                        self.handle_pointer_motion(p, rel)
                elif event.type == pygame.MOUSEBUTTONUP:
                    #print("UP event button:", getattr(event, "button", None))
                    p = self.map_pointer_pos(event.pos)
                    self.handle_pointer_up(p, buttons)



            # Render
            self.draw_frame()
            self.apply_brightness()
            if self.overlay_visible and not self.sleeping:
                # recreate buttons if resolution changed (rare)
                if buttons and (buttons[0].rect.bottom > self.screen.get_height() or buttons[0].rect.right > self.screen.get_width()):
                    buttons = make_buttons(sw, sh, self.cfg)
                self.draw_overlay(buttons)

            pygame.display.flip()
            clock.tick(self.cfg.target_fps)

        # persist on exit
        self.persist_state()
        pygame.quit()

def main() -> None:
    args = parse_args()

    home = os.path.expanduser("~")

    if os.name == "nt":
        default_photos = r"C:\PhotoFrame\photos"
        default_data = os.path.join(home, "PhotoFrameData")
    else:
        default_photos = "/mnt/photo-frame/photos"
        default_data = os.path.join(home, "photo-frame-data")

    fullscreen = not args.windowed
    if os.name == "nt":
        fullscreen = False   # dev: always windowed on Windows

    photos_dir = (
        args.photos
        or os.environ.get("PHOTO_FRAME_PHOTOS_DIR")
        or default_photos
    )
    data_dir = (
        args.data
        or os.environ.get("PHOTO_FRAME_DATA_DIR")
        or default_data
    )

    os.makedirs(data_dir, exist_ok=True)

    cfg = Config(
        photos_dir=photos_dir,
        data_dir=data_dir,
        fullscreen=fullscreen,
        slide_seconds=args.seconds,
        rescan_interval_sec=args.rescan,
    )
    #print("WINDOWED ARG:", args.windowed, "CFG FULLSCREEN:", cfg.fullscreen, "OS:", os.name)

    app = PhotoFrameApp(cfg)
    app.run()



if __name__ == "__main__":
    main()
