/* Minimal main program -- everything is loaded from the library */

#include "Python.h"

#ifdef MS_WINDOWS
int
wmain(int argc, wchar_t **argv)
{
    return Py_Main(argc, argv);
}
#else

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/stat.h>

extern char **environ;

int _main_wrapper(int argc, char **argv)
{
    char * ld_library_path_value = NULL;

    for (char** env_ptr = environ; *env_ptr != NULL; env_ptr++) {
        if (strncmp("LD_LIBRARY_PATH=", *env_ptr, 16) == 0) {
             ld_library_path_value = *env_ptr+16;
             printf("%s\n", ld_library_path_value);
            break;
        }
    }

    if (ld_library_path_value) {
        if (strncmp("/usr/lib/scalyr-agent-2/python3/lib:", ld_library_path_value, 36) == 0) {
            printf("ALREADY!!!!");
            return Py_BytesMain(argc, argv);
        }
    }

    size_t new_ld_library_path_len = strlen("/usr/lib/scalyr-agent-2/python3/lib:");
    if (ld_library_path_value)
        new_ld_library_path_len+=strlen(ld_library_path_value);

    char * new_ld_library_path_value = malloc(new_ld_library_path_len);
    strcpy(new_ld_library_path_value, "/usr/lib/scalyr-agent-2/python3/lib:");
    if (ld_library_path_value)
        strcpy(new_ld_library_path_value+36, ld_library_path_value);

    setenv("LD_LIBRARY_PATH", new_ld_library_path_value, 1);
    free(new_ld_library_path_value);
    printf("OVERRIDE\n");
    execv("/Users/arthur/PycharmProjects/scalyr-agent-2-final/main.o", argv);

    return 0;
}

int
main(int argc, char **argv)
{
    return _main_wrapper(argc, argv);
}
#endif
