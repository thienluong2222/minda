"""Vietnamese OCR and conservative reconstruction of ruled tables and text blocks."""

import itertools
import json
from collections import defaultdict

from meeting_backend.core.errors import AppError


def clusters(indices, gap=4):
    result = []
    for index in indices:
        if not result or index - result[-1][-1] > gap:
            result.append([int(index)])
        else:
            result[-1].append(int(index))
    return [round(sum(group) / len(group)) for group in result]


def extract_image(image, cache_dir, report_path):
    import cv2
    import numpy as np
    import pytesseract
    from PIL import ImageOps

    image = ImageOps.exif_transpose(image).convert("RGB")
    if image.width * image.height > 40_000_000:
        raise AppError(
            "IMAGE_TOO_LARGE", "Ảnh vượt 40 megapixel. Hãy giảm kích thước trước khi tải.", 422
        )
    if not (cache_dir / "vie.traineddata").is_file():
        raise AppError(
            "OCR_NOT_READY", "Chưa chuẩn bị trọng số OCR tiếng Việt. Chạy lệnh prepare-ocr.", 503
        )
    config = f'--tessdata-dir "{cache_dir}" --psm 3'
    data = pytesseract.image_to_data(
        image, lang="vie+eng", config=config, output_type=pytesseract.Output.DICT, timeout=120
    )
    words = []
    for i, text in enumerate(data["text"]):
        if text.strip():
            words.append(
                {
                    "text": text,
                    "x": data["left"][i],
                    "y": data["top"][i],
                    "w": data["width"][i],
                    "h": data["height"][i],
                    "confidence": float(data["conf"][i]),
                    "line": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
                }
            )
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, image.width // 25), 1)),
    )
    vertical = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, image.height // 25))),
    )
    grid = cv2.add(horizontal, vertical)
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < image.width * 0.25 or h < 50:
            continue
        xs = clusters(np.where((vertical[y : y + h, x : x + w] > 0).sum(axis=0) > h * 0.65)[0])
        ys = clusters(np.where((horizontal[y : y + h, x : x + w] > 0).sum(axis=1) > w * 0.65)[0])
        if not 2 <= len(xs) <= 15 or not 2 <= len(ys) <= 100:
            continue
        xs = [x + i for i in xs]
        ys = [y + i for i in ys]
        cells = []
        for top, bottom in itertools.pairwise(ys):
            row = []
            for left, right in itertools.pairwise(xs):
                selected = [
                    word
                    for word in words
                    if left <= word["x"] + word["w"] / 2 < right
                    and top <= word["y"] + word["h"] / 2 < bottom
                ]
                row.append(
                    " ".join(
                        word["text"]
                        for word in sorted(selected, key=lambda a: (a["y"] // 15, a["x"]))
                    )
                )
            cells.append(row)
        tables.append({"type": "table", "x": x, "y": y, "width": w, "height": h, "rows": cells})
    lines = defaultdict(list)
    for word in words:
        if any(
            t["x"] <= word["x"] + word["w"] / 2 <= t["x"] + t["width"]
            and t["y"] <= word["y"] + word["h"] / 2 <= t["y"] + t["height"]
            for t in tables
        ):
            continue
        lines[word["line"]].append(word)
    elements = list(tables)
    for values in lines.values():
        ordered = sorted(values, key=lambda a: a["x"])
        elements.append(
            {
                "type": "paragraph",
                "x": min(w["x"] for w in values),
                "y": min(w["y"] for w in values),
                "text": " ".join(w["text"] for w in ordered),
            }
        )
    elements.sort(key=lambda e: (e["y"], e["x"]))
    low = [w for w in words if w["confidence"] < 65]
    report = {
        "width": image.width,
        "height": image.height,
        "word_count": len(words),
        "mean_confidence": sum(w["confidence"] for w in words) / len(words) if words else None,
        "low_confidence_count": len(low),
        "low_confidence_samples": [w["text"] for w in low[:30]],
        "table_count": len(tables),
        "words": words,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    summary = {key: value for key, value in report.items() if key != "words"}
    return elements, summary
