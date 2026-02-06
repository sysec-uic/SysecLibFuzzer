#ifndef FUZZER_XRAY_H
#define FUZZER_XRAY_H

#include <cstddef>
#include <cstdint>
#include <string>

namespace fuzzer {

class XRayTrace {
 public:
  void Initialize(const std::string &OutputDir, bool TraceOnlyOnCorpus);
  bool Enabled() const;
  void StartNewInput();
  void Stop();
  void Dump(const uint8_t *Data, size_t Size);
  void SetTraceOnlyOnCorpus(bool Value);
  bool TraceOnlyOnCorpus() const;

 private:
  bool EnabledFlag = false;
  bool TraceOnlyOnCorpusFlag = false;
  std::string OutputDir;
};

extern XRayTrace XR;

}  // namespace fuzzer

#endif  // FUZZER_XRAY_H
