// ARVO harness for libxml2 xmlReadMemory.
// Takes raw XML bytes as input (no fuzz format wrapper).
// From: https://github.com/nicktehrany/ARVO (Chromium OSS-Fuzz)

#include <cassert>
#include <cstddef>
#include <cstdint>

#include <functional>
#include <limits>
#include <string>

#include "libxml/parser.h"
#include "libxml/xmlsave.h"

void ignore(void *ctx, const char *msg, ...) {}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    xmlSetGenericErrorFunc(NULL, &ignore);

    std::string data_string(reinterpret_cast<const char *>(data), size);
    const std::size_t data_hash = std::hash<std::string>()(data_string);
    const int max_option_value = std::numeric_limits<int>::max();
    int random_option_value = data_hash % max_option_value;

    // Disable XML_PARSE_HUGE to avoid stack overflow.
    random_option_value &= ~XML_PARSE_HUGE;
    const int options[] = {0, random_option_value};

    for (const auto option_value : options) {
        if (auto doc = xmlReadMemory(data_string.c_str(), data_string.length(),
                                     "noname.xml", NULL, option_value)) {
            auto buf = xmlBufferCreate();
            assert(buf);
            auto ctxt = xmlSaveToBuffer(buf, NULL, 0);
            xmlSaveDoc(ctxt, doc);
            xmlSaveClose(ctxt);
            xmlFreeDoc(doc);
            xmlBufferFree(buf);
        }
    }

    return 0;
}
