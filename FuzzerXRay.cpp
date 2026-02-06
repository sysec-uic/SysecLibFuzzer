#include "FuzzerXRay.h"

#include "FuzzerUtil.h"

#include <atomic>
#include <cinttypes>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#if defined(__has_include)
#if __has_include(<cxxabi.h>)
#include <cxxabi.h>
#define FUZZER_HAVE_CXXABI 1
#else
#define FUZZER_HAVE_CXXABI 0
#endif
#else
#include <cxxabi.h>
#define FUZZER_HAVE_CXXABI 1
#endif
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#if defined(__has_attribute)
#if __has_attribute(xray_never_instrument)
#define FUZZER_XRAY_NOINSTR __attribute__((xray_never_instrument))
#else
#define FUZZER_XRAY_NOINSTR
#endif
#else
#define FUZZER_XRAY_NOINSTR
#endif

extern "C" {
enum XRayEntryType {
  XRAY_ENTRY = 0,
  XRAY_EXIT = 1,
  XRAY_TAIL = 2,
};

enum XRayPatchingStatus {
  XRAY_NOT_INITIALIZED = 0,
  XRAY_SUCCESS = 1,
  XRAY_ONGOING = 2,
  XRAY_FAILED = 3,
};

int __xray_set_handler(void (*entry)(int32_t, XRayEntryType))
    __attribute__((weak));
int __xray_remove_handler() __attribute__((weak));
XRayPatchingStatus __xray_patch() __attribute__((weak));
XRayPatchingStatus __xray_unpatch() __attribute__((weak));
uintptr_t __xray_function_address(int32_t FuncId) __attribute__((weak));
void __xray_init() __attribute__((weak));
}

namespace fuzzer {
namespace {

struct XRayEvent {
  int32_t FuncId;
  uint8_t Type;
};

constexpr size_t kDefaultMaxEvents = 1000000;

FUZZER_XRAY_NOINSTR std::vector<XRayEvent> &Buffer() {
  static std::vector<XRayEvent> Buf;
  return Buf;
}

FUZZER_XRAY_NOINSTR std::atomic<size_t> &Index() {
  static std::atomic<size_t> Idx{0};
  return Idx;
}

FUZZER_XRAY_NOINSTR std::atomic<bool> &Active() {
  static std::atomic<bool> A{false};
  return A;
}

FUZZER_XRAY_NOINSTR std::atomic<bool> &Overflowed() {
  static std::atomic<bool> O{false};
  return O;
}

FUZZER_XRAY_NOINSTR void XRayHandler(int32_t FuncId, XRayEntryType Type) {
  if (!Active().load(std::memory_order_relaxed))
    return;
  size_t I = Index().fetch_add(1, std::memory_order_relaxed);
  auto &Buf = Buffer();
  if (I >= Buf.size()) {
    Overflowed().store(true, std::memory_order_relaxed);
    return;
  }
  Buf[I] = {FuncId, static_cast<uint8_t>(Type)};
}

bool XRayAvailable() {
  return __xray_set_handler && __xray_patch && __xray_function_address;
}

std::string Chomp(std::string S) {
  while (!S.empty() && (S.back() == '\n' || S.back() == '\r' ||
                        S.back() == ' ' || S.back() == '\t'))
    S.pop_back();
  return S;
}

std::string Demangle(const char *Name) {
  if (!Name || !Name[0])
    return "";
#if FUZZER_HAVE_CXXABI
  int Status = 0;
  char *Out = abi::__cxa_demangle(Name, nullptr, nullptr, &Status);
  if (Status == 0 && Out) {
    std::string S(Out);
    std::free(Out);
    return S;
  }
  std::free(Out);
  return std::string(Name);
#else
  return std::string(Name);
#endif
}

std::string DladdrFunctionName(uintptr_t Addr) {
  Dl_info Info;
  std::memset(&Info, 0, sizeof(Info));
  if (!dladdr(reinterpret_cast<void *>(Addr), &Info))
    return "";
  if (!Info.dli_sname || !Info.dli_sname[0])
    return "";
  return Demangle(Info.dli_sname);
}

std::string JsonEscape(const std::string &In) {
  std::string Out;
  Out.reserve(In.size());
  for (unsigned char C : In) {
    switch (C) {
    case '"':
      Out += "\\\"";
      break;
    case '\\':
      Out += "\\\\";
      break;
    case '\b':
      Out += "\\b";
      break;
    case '\f':
      Out += "\\f";
      break;
    case '\n':
      Out += "\\n";
      break;
    case '\r':
      Out += "\\r";
      break;
    case '\t':
      Out += "\\t";
      break;
    default:
      if (C < 0x20) {
        char Buf[7];
        std::snprintf(Buf, sizeof(Buf), "\\u%04x", C);
        Out += Buf;
      } else {
        Out.push_back(static_cast<char>(C));
      }
      break;
    }
  }
  return Out;
}

std::string XRayFunctionName(int32_t FuncId,
                             std::unordered_map<int32_t, std::string> &Cache) {
  auto It = Cache.find(FuncId);
  if (It != Cache.end())
    return It->second;
  uintptr_t Addr = __xray_function_address(FuncId);
  if (!Addr) {
    Cache.emplace(FuncId, "<unknown>");
    return "<unknown>";
  }
  // libFuzzer's DescribePC uses __sanitizer_symbolize_pc, which is only
  // available when linked with a sanitizer runtime. In pure-XRay builds we
  // fall back to dladdr() (requires linking the target with -rdynamic /
  // -Wl,--export-dynamic for best results).
  std::string Name = Chomp(DescribePC("%F", Addr));
  if (Name.empty() || Name == "<can not symbolize>")
    Name = DladdrFunctionName(Addr);
  if (Name.empty())
    Name = "<unknown>";
  Cache.emplace(FuncId, Name);
  return Name;
}

std::string XRayFunctionAddrHex(int32_t FuncId) {
  uintptr_t Addr = __xray_function_address(FuncId);
  if (!Addr)
    return "0x0";
  char Buf[32];
  std::snprintf(Buf, sizeof(Buf), "0x%" PRIxPTR, Addr);
  return std::string(Buf);
}

}  // namespace

XRayTrace XR;

void XRayTrace::Initialize(const std::string &OutDir,
                           bool TraceOnlyOnCorpus) {
  OutputDir = OutDir;
  TraceOnlyOnCorpusFlag = TraceOnlyOnCorpus;

  if (!XRayAvailable()) {
    Printf("WARNING: XRay runtime not available; xray tracing disabled.\n");
    EnabledFlag = false;
    return;
  }

  if (__xray_init)
    __xray_init();

  if (__xray_set_handler(XRayHandler) != 1) {
    Printf("WARNING: Failed to set XRay handler; xray tracing disabled.\n");
    EnabledFlag = false;
    return;
  }

  XRayPatchingStatus Status = __xray_patch();
  if (Status != XRAY_SUCCESS) {
    Printf("WARNING: XRay patching failed; xray tracing disabled.\n");
    EnabledFlag = false;
    return;
  }

  Buffer().assign(kDefaultMaxEvents, XRayEvent{0, 0});
  Index().store(0, std::memory_order_relaxed);
  Active().store(false, std::memory_order_relaxed);
  Overflowed().store(false, std::memory_order_relaxed);
  EnabledFlag = true;
}

bool XRayTrace::Enabled() const { return EnabledFlag; }

void XRayTrace::SetTraceOnlyOnCorpus(bool Value) {
  TraceOnlyOnCorpusFlag = Value;
}

bool XRayTrace::TraceOnlyOnCorpus() const { return TraceOnlyOnCorpusFlag; }

void XRayTrace::StartNewInput() {
  if (!EnabledFlag)
    return;
  Index().store(0, std::memory_order_relaxed);
  Overflowed().store(false, std::memory_order_relaxed);
  Active().store(true, std::memory_order_relaxed);
}

void XRayTrace::Stop() {
  if (!EnabledFlag)
    return;
  Active().store(false, std::memory_order_relaxed);
}

void XRayTrace::Dump(const uint8_t *Data, size_t Size) {
  if (!EnabledFlag || OutputDir.empty())
    return;

  size_t Count = Index().load(std::memory_order_relaxed);
  if (Count == 0)
    return;
  if (Count > Buffer().size())
    Count = Buffer().size();

  uint64_t Hash = SimpleFastHash(Data, Size, 0);
  char HashStr[32];
  snprintf(HashStr, sizeof(HashStr), "%016llx",
           (unsigned long long)Hash);

  std::string Filename = OutputDir + "/" + std::string(HashStr) + ".xray.json";
  FILE *F = fopen(Filename.c_str(), "w");
  if (!F) {
    Printf("WARNING: Failed to open xray trace file: %s\n", Filename.c_str());
    return;
  }

  std::unordered_map<int32_t, std::string> NameCache;
  std::unordered_map<int32_t, size_t> HitCounts;
  std::unordered_map<int32_t, std::string> AddrCache;

  fprintf(F, "{\n");
  fprintf(F, "  \"input_hash\": \"%s\",\n", HashStr);
  fprintf(F, "  \"input_size\": %zu,\n", Size);
  fprintf(F, "  \"event_count\": %zu,\n", Count);
  fprintf(F, "  \"overflow\": %s,\n",
          Overflowed().load(std::memory_order_relaxed) ? "true" : "false");
  fprintf(F, "  \"events\": [\n");

  auto &Buf = Buffer();
  for (size_t I = 0; I < Count; ++I) {
    const auto &E = Buf[I];
    HitCounts[E.FuncId]++;
    (void)XRayFunctionName(E.FuncId, NameCache);
    if (AddrCache.find(E.FuncId) == AddrCache.end())
      AddrCache.emplace(E.FuncId, XRayFunctionAddrHex(E.FuncId));
    fprintf(F, "    {\"id\": %d, \"type\": %u}",
            E.FuncId, static_cast<unsigned>(E.Type));
    if (I + 1 < Count)
      fprintf(F, ",");
    fprintf(F, "\n");
  }
  fprintf(F, "  ],\n");

  // Emit a per-function lookup table so traces can be symbolized offline even
  // when runtime symbolization is unavailable.
  fprintf(F, "  \"functions\": {\n");
  {
    bool First = true;
    for (const auto &KV : HitCounts) {
      int32_t FuncId = KV.first;
      const std::string &Name = NameCache[FuncId];
      const std::string &Addr = AddrCache[FuncId];
      if (!First)
        fprintf(F, ",\n");
      First = false;
      fprintf(F, "    \"%d\": {\"name\": \"%s\", \"addr\": \"%s\"}",
              FuncId, JsonEscape(Name).c_str(), Addr.c_str());
    }
    fprintf(F, "\n");
  }
  fprintf(F, "  },\n");

  fprintf(F, "  \"counts\": {\n");
  {
    size_t Printed = 0;
    for (const auto &KV : HitCounts) {
      fprintf(F, "    \"%d\": %zu", KV.first, KV.second);
      Printed++;
      if (Printed < HitCounts.size())
        fprintf(F, ",");
      fprintf(F, "\n");
    }
  }
  fprintf(F, "  }\n");
  fprintf(F, "}\n");
  fclose(F);
}

}  // namespace fuzzer
