/* e9patch hook: logs call instructions with temporal ordering. */
#include "stdlib.c"

static int g_seq = 0;

/* Per-target call counting. Keyed on target address. */
#define HT_SIZE 256

struct ht_entry {
    uintptr_t addr;
    int       count;
    int       used;
};

static struct ht_entry g_counts[HT_SIZE];

static int hash_addr(uintptr_t a) {
    a ^= a >> 16;
    a *= 0x45d9f3b;
    a ^= a >> 16;
    return (int)(a & (HT_SIZE - 1));
}

static int get_and_inc(uintptr_t addr) {
    int idx = hash_addr(addr);
    for (int i = 0; i < HT_SIZE; i++) {
        int slot = (idx + i) & (HT_SIZE - 1);
        if (g_counts[slot].used && g_counts[slot].addr == addr)
            return ++g_counts[slot].count;
        if (!g_counts[slot].used) {
            g_counts[slot].addr = addr;
            g_counts[slot].count = 1;
            g_counts[slot].used = 1;
            return 1;
        }
    }
    return -1;
}

/* Write hex value into buf, return chars written. */
static int hex_buf(char *buf, uintptr_t val) {
    const char h[] = "0123456789abcdef";
    if (val == 0) { buf[0] = '0'; return 1; }
    char tmp[16]; int n = 0;
    while (val > 0) { tmp[n++] = h[val & 0xf]; val >>= 4; }
    for (int i = n - 1; i >= 0; i--) buf[i] = tmp[n - 1 - i];
    return n;
}

/* Write decimal value into buf, return chars written. */
static int dec_buf(char *buf, int val) {
    if (val <= 0) { buf[0] = '0'; return 1; }
    char tmp[16]; int n = 0;
    while (val > 0) { tmp[n++] = '0' + (val % 10); val /= 10; }
    for (int i = 0; i < n; i++) buf[i] = tmp[n - 1 - i];
    return n;
}

static void append(char *buf, int *pos, const char *s) {
    while (*s) buf[(*pos)++] = *s++;
}

void entry(const void *target) {
    g_seq++;
    int call_id = get_and_inc((uintptr_t)target);

    char buf[128];
    int pos = 0;

    append(buf, &pos, "TRACE seq=");
    pos += dec_buf(buf + pos, g_seq);
    append(buf, &pos, " target=0x");
    pos += hex_buf(buf + pos, (uintptr_t)target);
    append(buf, &pos, " call_id=");
    pos += dec_buf(buf + pos, call_id);
    buf[pos++] = '\n';

    write(STDERR_FILENO, buf, pos);
}

void init(int argc, char **argv, char **envp) {
    environ = envp;
}

void trace_reset(void) {
    g_seq = 0;
    for (int i = 0; i < HT_SIZE; i++) {
        g_counts[i].used = 0;
        g_counts[i].count = 0;
    }
}
