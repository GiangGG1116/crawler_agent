#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

/*
 * Minimal setuid launcher for Bubblewrap inside Docker.
 *
 * The caller can choose only the contents of runner.py. Every namespace,
 * mount, capability, executable, and environment option is fixed here.
 */
int main(int argc, char **argv) {
    const char *prefix = "/tmp/agent-sandbox-";
    const char *suffix = "/runner.py";
    uid_t caller_uid = getuid();
    struct stat runner_stat;
    char resolved[PATH_MAX];
    char fd_arg[32];

    if (argc != 2 || realpath(argv[1], resolved) == NULL) {
        fprintf(stderr, "sandbox launcher requires one valid runner path\n");
        return 64;
    }
    size_t path_len = strlen(resolved);
    size_t suffix_len = strlen(suffix);
    if (strncmp(resolved, prefix, strlen(prefix)) != 0 ||
        path_len <= suffix_len ||
        strcmp(resolved + path_len - suffix_len, suffix) != 0) {
        fprintf(stderr, "runner path is outside the approved temporary directory\n");
        return 65;
    }

    int runner_fd = open(resolved, O_RDONLY | O_NOFOLLOW);
    if (runner_fd < 0 || fstat(runner_fd, &runner_stat) != 0) {
        perror("failed to open runner");
        return 66;
    }
    if (!S_ISREG(runner_stat.st_mode) || runner_stat.st_uid != caller_uid ||
        (runner_stat.st_mode & (S_IWGRP | S_IWOTH)) != 0) {
        fprintf(stderr, "runner ownership or permissions are unsafe\n");
        return 67;
    }
    int fd_flags = fcntl(runner_fd, F_GETFD);
    if (fd_flags < 0 || fcntl(runner_fd, F_SETFD, fd_flags & ~FD_CLOEXEC) != 0) {
        perror("failed to preserve runner descriptor");
        return 68;
    }
    snprintf(fd_arg, sizeof(fd_arg), "%d", runner_fd);

    if (clearenv() != 0 || setresgid(0, 0, 0) != 0 || setresuid(0, 0, 0) != 0) {
        perror("failed to prepare sandbox privileges");
        return 69;
    }

    char *const sandbox_argv[] = {
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--dir",
        "/etc",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--ro-bind",
        "/etc/ssl",
        "/etc/ssl",
        "--ro-bind",
        "/etc/resolv.conf",
        "/etc/resolv.conf",
        "--ro-bind",
        "/etc/hosts",
        "/etc/hosts",
        "--dir",
        "/sandbox",
        "--ro-bind-data",
        fd_arg,
        "/sandbox/runner.py",
        "--tmpfs",
        "/tmp",
        "--chdir",
        "/sandbox",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--cap-drop",
        "ALL",
        "/usr/local/bin/python",
        "/sandbox/runner.py",
        NULL,
    };
    execv(sandbox_argv[0], sandbox_argv);
    perror("failed to execute bubblewrap");
    return errno == ENOENT ? 127 : 70;
}
