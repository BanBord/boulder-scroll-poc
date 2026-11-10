import Foundation
import Vision
import CoreImage

// usage: personseg <inDir> <outDir>  -> one 8-bit grey mask PNG per input frame (white = person)
let args = CommandLine.arguments
let inDir = URL(fileURLWithPath: args[1])
let outDir = URL(fileURLWithPath: args[2])
let ctx = CIContext()
let files = try FileManager.default.contentsOfDirectory(at: inDir, includingPropertiesForKeys: nil)
    .filter { ["png", "jpg", "jpeg"].contains($0.pathExtension.lowercased()) }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }
let req = VNGeneratePersonSegmentationRequest()
req.qualityLevel = .accurate
req.outputPixelFormat = kCVPixelFormatType_OneComponent8
var done = 0
for f in files {
    guard let ci = CIImage(contentsOf: f) else { continue }
    let handler = VNImageRequestHandler(ciImage: ci, options: [:])
    try handler.perform([req])
    guard let pb = req.results?.first?.pixelBuffer else { continue }
    var m = CIImage(cvPixelBuffer: pb)
    m = m.transformed(by: CGAffineTransform(scaleX: ci.extent.width / m.extent.width,
                                            y: ci.extent.height / m.extent.height))
    let out = outDir.appendingPathComponent(f.deletingPathExtension().lastPathComponent + ".png")
    try ctx.writePNGRepresentation(of: m, to: out, format: .L8,
                                   colorSpace: CGColorSpace(name: CGColorSpace.linearGray)!)
    done += 1
}
print("masks written: \(done) of \(files.count)")
