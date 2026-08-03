#!/usr/bin/env python3
"""Render an SVG asset to a pixel-perfect PNG using macOS AppKit."""

import argparse
from pathlib import Path

from AppKit import (
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSCalibratedRGBColorSpace,
    NSCompositingOperationCopy,
    NSGraphicsContext,
    NSImage,
)
from Foundation import NSMakeRect, NSZeroRect


def render(source: Path, destination: Path, width: int, height: int) -> None:
    image = NSImage.alloc().initWithContentsOfFile_(str(source.resolve()))
    if image is None:
        raise SystemExit(f"Unable to load {source}")

    bitmap = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None,
        width,
        height,
        8,
        4,
        True,
        False,
        NSCalibratedRGBColorSpace,
        0,
        0,
    )
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
    NSGraphicsContext.saveGraphicsState()
    try:
        NSGraphicsContext.setCurrentContext_(context)
        image.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, width, height),
            NSZeroRect,
            NSCompositingOperationCopy,
            1.0,
        )
        context.flushGraphics()
    finally:
        NSGraphicsContext.restoreGraphicsState()

    data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    destination.write_bytes(bytes(data))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    args = parser.parse_args()
    render(args.source, args.destination, args.width, args.height)


if __name__ == "__main__":
    main()
