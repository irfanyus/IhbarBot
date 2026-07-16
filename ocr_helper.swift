import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else {
    print("Error: Missing image path argument.")
    exit(1)
}

let imagePath = CommandLine.arguments[1]
let imageUrl = URL(fileURLWithPath: imagePath)

guard let image = NSImage(contentsOf: imageUrl),
      let tiffData = image.tiffRepresentation,
      let cgImageSource = CGImageSourceCreateWithData(tiffData as CFData, nil),
      let cgImage = CGImageSourceCreateImageAtIndex(cgImageSource, 0, nil) else {
    print("Error: Failed to load image.")
    exit(1)
}

let requestHandler = VNImageRequestHandler(cgImage: cgImage, options: [:])
let request = VNRecognizeTextRequest { request, error in
    if let error = error {
        print("Error during text recognition: \(error)")
        return
    }
    
    guard let observations = request.results as? [VNRecognizedTextObservation] else { return }
    
    for observation in observations {
        if let topCandidate = observation.topCandidates(1).first {
            print(topCandidate.string)
        }
    }
}

request.recognitionLevel = .accurate
request.usesLanguageCorrection = false

do {
    try requestHandler.perform([request])
} catch {
    print("Error performing OCR request: \(error)")
}
