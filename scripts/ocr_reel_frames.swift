import AVFoundation
import Vision
import CoreGraphics
import Foundation

let args = CommandLine.arguments
if args.count < 4 || args.count > 5 {
  fputs("usage: ocr_reel_frames.swift VIDEO LANGUAGE OUTPUT [INTERVAL]\n", stderr)
  exit(2)
}

let asset = AVURLAsset(url: URL(fileURLWithPath: args[1]))
let duration = CMTimeGetSeconds(asset.duration)
if !duration.isFinite || duration <= 0 {
  fputs("OCR asset has no readable duration\n", stderr)
  exit(3)
}

let interval = args.count == 5 ? (Double(args[4]) ?? 0.5) : 0.5
let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = .zero
generator.requestedTimeToleranceAfter = .zero

let locales = args[2].split(separator: ",").map(String.init)
var rows: [[String: Any]] = []

func cropCaptionBand(_ image: CGImage) -> CGImage {
  let height = image.height
  let width = image.width
  let band = max(1, Int(Double(height) * 0.34))
  let rect = CGRect(x: 0, y: height - band, width: width, height: band)
  return image.cropping(to: rect) ?? image
}

var second = 0.0
while second <= duration + 0.0001 {
  let time = CMTime(seconds: min(second, duration), preferredTimescale: 600)
  guard let full = try? generator.copyCGImage(at: time, actualTime: nil) else {
    second += interval
    continue
  }
  let image = cropCaptionBand(full)
  let request = VNRecognizeTextRequest()
  request.recognitionLevel = .accurate
  request.usesLanguageCorrection = true
  if let supported = try? request.supportedRecognitionLanguages() {
    let chosen = locales.filter { supported.contains($0) }
    if !chosen.isEmpty { request.recognitionLanguages = chosen }
  }
  let handler = VNImageRequestHandler(cgImage: image, options: [:])
  guard (try? handler.perform([request])) != nil else {
    second += interval
    continue
  }
  let text = (request.results ?? [])
    .compactMap { $0.topCandidates(1).first?.string }
    .joined(separator: " ")
    .trimmingCharacters(in: .whitespacesAndNewlines)
  if !text.isEmpty {
    rows.append([
      "start": second,
      "end": min(second + interval, duration),
      "text": text,
    ])
  }
  second += interval
}

let data = try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys])
try data.write(to: URL(fileURLWithPath: args[3]))
