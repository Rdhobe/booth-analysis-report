"""Stage 1-2: render PDF pages to upright, de-skewed grayscale images."""
import math

import cv2
import fitz  # PyMuPDF
import numpy as np

TARGET_WIDTH = 2600  # px; the scans are ~100-200 DPI, Tesseract likes larger text


def page_count(pdf_path):
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def render_page(pdf_path, page_idx, target_width=TARGET_WIDTH):
    """Render one page to a grayscale array. PyMuPDF applies the page's
    rotation flag, so scans stored upside-down come out upright."""
    with fitz.open(pdf_path) as doc:
        page = doc[page_idx]
        zoom = target_width / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.stride)[:, : pix.w].copy()


def binarize(gray):
    """White ink on black background."""
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )


def estimate_skew(gray):
    """Median angle (degrees) of the long near-horizontal table lines.
    Measured on a half-size copy for speed."""
    small = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    bw = binarize(small)
    h, w = bw.shape
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (w // 30, 1)))
    lines = cv2.HoughLinesP(
        hor, 1, np.pi / 1800, threshold=60, minLineLength=w // 4, maxLineGap=w // 40
    )
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = x2 - x1, y2 - y1
        if dx > 0 and abs(dy / dx) < 0.1:
            angles.append(math.degrees(math.atan2(dy, dx)))
    return float(np.median(angles)) if angles else 0.0


def deskew(gray):
    angle = estimate_skew(gray)
    if abs(angle) < 0.1:
        return gray, angle
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)
    return out, angle


def load_page(pdf_path, page_idx):
    """Render + deskew. Returns (gray, skew_angle)."""
    return deskew(render_page(pdf_path, page_idx))
