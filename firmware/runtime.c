#include <stddef.h>

void *memset(void *dest, int value, size_t len)
{
    unsigned char *out = (unsigned char *)dest;

    while (len-- != 0U) {
        *out++ = (unsigned char)value;
    }

    return dest;
}

void *memcpy(void *dest, const void *src, size_t len)
{
    unsigned char *out = (unsigned char *)dest;
    const unsigned char *in = (const unsigned char *)src;

    while (len-- != 0U) {
        *out++ = *in++;
    }

    return dest;
}