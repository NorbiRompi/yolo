"""Rekonstrukcja obrazu z etykiet YOLO - pojedyncza klatka albo sekwencja.

Wymaga: pip install pillow

Użycie:
  python yolo_reconstruct.py                  -> folder labels/ (jeśli jest), inaczej plik labels.txt
  python yolo_reconstruct.py labels/          -> odtwarzanie sekwencji 0000001.txt, 0000002.txt, ...
  python yolo_reconstruct.py labels/ --fps 15 -> prędkość odtwarzania (domyślnie 30 klatek/s)
  python yolo_reconstruct.py labels.txt       -> pojedyncza klatka

Klawisze w oknie: Spacja = pauza, Esc = wyjście.
Gdy skończą się pliki, program czeka na nowe (tryb "na żywo") - pliki mogą dochodzić w trakcie.
Sprite'y: sprites/<id_klasy>.png|jpg|... Brak pliku -> kolorowy prostokąt z numerem klasy.
"""
import argparse
import re
import time
from pathlib import Path
from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent      # ścieżki liczone od folderu skryptu
SPRITES_DIR = BASE / "sprites"
EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
W, H = 1280, 720                            # rozmiar płótna (dane są znormalizowane)

_sprites = {}      # klasa -> oryginalny sprite (ładowany raz, przy pierwszym użyciu)
_resized = {}      # (klasa, szer., wys.) -> przeskalowany sprite (cache)


def load_labels(path):
    boxes = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 5:
                continue
            boxes.append((int(parts[0]), *map(float, parts[1:5])))
    return boxes


def make_placeholder(cls):
    img = Image.new("RGBA", (200, 200), (
        (cls * 67) % 200 + 40, (cls * 131) % 200 + 40, (cls * 29) % 200 + 40, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 199, 199], outline=(255, 255, 255, 255), width=4)
    d.text((10, 10), f"class {cls}", fill=(255, 255, 255, 255))
    return img


def get_sprite(cls):
    if cls not in _sprites:
        path = next((SPRITES_DIR / f"{cls}{e}" for e in EXTS
                     if (SPRITES_DIR / f"{cls}{e}").exists()), None)
        if path:
            _sprites[cls] = Image.open(path).convert("RGBA")
        else:
            print(f"Brak sprite'a dla klasy {cls} w {SPRITES_DIR} - rysuję zastępczy prostokąt")
            _sprites[cls] = make_placeholder(cls)
    return _sprites[cls]


def get_resized(cls, bw, bh):
    key = (cls, bw, bh)
    if key not in _resized:
        if len(_resized) > 3000:            # żeby cache nie rósł w nieskończoność
            _resized.clear()
        _resized[key] = get_sprite(cls).resize((bw, bh), Image.BILINEAR)
    return _resized[key]


def render(boxes, size=(W, H)):
    cw, ch = size
    canvas = Image.new("RGB", size, (30, 30, 30))
    # od największych do najmniejszych, żeby małe obiekty były na wierzchu
    for cls, xc, yc, w, h in sorted(boxes, key=lambda b: b[3] * b[4], reverse=True):
        bw, bh = max(1, round(w * cw)), max(1, round(h * ch))
        sprite = get_resized(cls, bw, bh)
        canvas.paste(sprite, (round(xc * cw - bw / 2), round(yc * ch - bh / 2)), sprite)
    return canvas


class FrameSequence:
    """Czyta po kolei pliki 0000001.txt, 0000002.txt, ... z folderu."""

    def __init__(self, folder):
        self.folder = Path(folder)
        nums = self._numbers()
        if not nums:
            raise SystemExit(f"Brak plików z numerem w nazwie (np. 0000001.txt) w {self.folder}")
        self.n = min(nums)
        self.width = len(next(self.folder.glob("*.txt")).stem)   # szerokość numeracji (np. 7)

    def _numbers(self):
        return [int(p.stem) for p in self.folder.glob("*.txt") if re.fullmatch(r"\d+", p.stem)]

    def next_frame(self):
        """Zwraca (numer, obraz) albo None, jeśli nowej klatki jeszcze nie ma."""
        path = self.folder / f"{self.n:0{self.width}d}.txt"
        if not path.exists():
            later = [x for x in self._numbers() if x > self.n]   # luka w numeracji -> przeskocz
            if not later:
                return None
            self.n = min(later)
            path = self.folder / f"{self.n:0{self.width}d}.txt"
        num = self.n
        self.n += 1
        return num, render(load_labels(path))


def run_window(next_image, fps=30.0, title="Rekonstrukcja"):
    """next_image() -> (opis, obraz) lub None (brak nowej klatki)."""
    import tkinter as tk
    from PIL import ImageTk

    interval = 1.0 / fps
    root = tk.Tk()
    root.title(title)
    label = tk.Label(root)
    label.pack()
    state = {"paused": False, "photo": None}

    def tick():
        t0 = time.perf_counter()
        wait = interval
        if not state["paused"]:
            result = next_image()
            if result is None:
                root.title(f"{title} - czekam na nowe klatki...")
                wait = 0.1
            else:
                desc, img = result
                state["photo"] = ImageTk.PhotoImage(img)   # trzymamy referencję, inaczej zniknie
                label.configure(image=state["photo"])
                root.title(f"{title} - klatka {desc}")
                wait = max(0.001, interval - (time.perf_counter() - t0))
        root.after(int(wait * 1000), tick)

    def toggle(_):
        state["paused"] = not state["paused"]

    root.bind("<space>", toggle)
    root.bind("<Escape>", lambda e: root.destroy())
    tick()
    root.mainloop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="folder z klatkami albo pojedynczy plik .txt")
    ap.add_argument("--fps", type=float, default=30.0)
    args = ap.parse_args()

    if args.path:
        path = Path(args.path)
    else:
        path = BASE / "labels" if (BASE / "labels").is_dir() else BASE / "labels.txt"

    if path.is_dir():
        seq = FrameSequence(path)
        run_window(seq.next_frame, fps=args.fps)
    else:
        img = render(load_labels(path))
        shown = [False]

        def once():                       # jedna klatka: pokaż raz, potem tylko czekaj
            if shown[0]:
                return None
            shown[0] = True
            return path.name, img
        run_window(once, fps=args.fps)