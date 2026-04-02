// Toy target to test e9patch function-entry hooking.
// Simulates a call chain similar to a crash stack trace.
// Build: clang -O1 -g -o target target.c
#include <stdio.h>
#include <stdlib.h>

void parse_header(const char *data, int len) {
    printf("  parse_header called (len=%d)\n", len);
}

void decode_frame(const char *data, int len) {
    printf("  decode_frame called (len=%d)\n", len);
    if (len > 5)
        parse_header(data, len / 2);
}

void validate_input(const char *data, int len) {
    printf("  validate_input called (len=%d)\n", len);
    for (int i = 0; i < 3 && i < len; i++)
        decode_frame(data + i, len - i);
}

int main(int argc, char **argv) {
    const char *input = argc > 1 ? argv[1] : "ABCDEFGH";
    int len = 0;
    while (input[len]) len++;

    printf("Processing input (%d bytes)...\n", len);
    validate_input(input, len);
    printf("Done.\n");
    return 0;
}
