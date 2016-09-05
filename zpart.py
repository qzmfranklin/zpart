#!/usr/bin/env python3

import argparse
import colored
from datetime import datetime
from easyshell import shell
import easycompleter
import json
import os
import subprocess
import textwrap
import time
import traceback

class KpartxShell(shell.Shell):
    pass

class LibguestfsShell(shell.Shell):
    pass


class ImageShell(shell.Shell):

    def __init__(self, *args, **kwargs):
        super(ImageShell, self).__init__(*args, **kwargs)

        self._format = None
        self._size = None
        self.__ls_cache = {
                'ls-dev': None,
                'ls-fs': None,
                'ls-part': None,
        }
        if os.path.isfile(self._file):
            self.__update_attrs_by_fname(self._file)
            self.__mtime = datetime.fromtimestamp(os.path.getmtime(self._file))

    def __update_attrs_by_fname(self, fname):
        """Use `qemu-img info` to determine attributes."""
        try:
            raw = subprocess.check_output('qemu-img info --output json {}'.
                    format(fname), shell = True).decode()
            d = json.loads(raw)
            self._format = d['format']
            self._size = str(d['virtual-size'])
        except subprocess.CalledProcessError:
            pass

    @property
    def _file(self):
        return self._mode_stack[-1].args[0]

    @shell.command('set')
    def do_set(self, cmd, args):
        """\
        Set a disk attribute.
            set <attribute> <value>

            <attribute> is one of
                file                The complete filename of the disk image.
                format              The format of the disk image, one of {raw,qcow2}.
                size                Virtual size of the disk image. You may use k, M, G, T,
                                    P or E suffixes for kilobytes, megabytes, gigabytes,
                                    terabytes, petabytes, and exabytes. Note that 1k = 1024
                                    here. If you just supply a positive integer, it is the
                                    number of bytes.

        To see the current values of attributes, use the 'get' command.
        """
        if len(args) != 2:
            self.stderr.write('set: requires 2 arguments, {} are supplied.'.
                    format(len(args)))
            self.stderr.write('\n')
            return

        attr = args[0]
        if not attr in self.__attrs:
            self.stderr.write("get: illegal argument '{}', must be one of {}.".
                    format(attr, self.__attrs))
            self.stderr.write('\n')
        else:
            setattr(self, '_' + attr, args[1])

    @shell.completer('set')
    def complete_set(self, cmd, args, text):
        if not args:
            return [ x for x in self.__attrs if x.startswith(text) ]

        if len(args) == 1 and args[0] == 'format':
            return [ x for x in {'qcow2', 'raw'} if x.startswith(text) ]

    __attrs = [ 'file', 'format', 'size', ]
    @shell.command('get')
    def do_show(self, cmd, args):
        """\
        Show disk attribute(s).
            get                 Show all attributes.
            get <attribute>     Show an attribute.

        To see what attributes are available, use the 'set' command.
        """
        if not args:
            for attr in self.__attrs:
                print('{}:\t\t{}'.format(attr, getattr(self, '_' + attr)))
            return
        elif len(args) > 1:
            self.stderr.write('get: requires 0 or 1 argument, {} are supplied.'.
                    format(len(args)))
            self.stderr.write('\n')
            return

        attr = args[0]
        if not attr in self.__attrs:
            self.stderr.write("get: illegal argument '{}', must be one of {}.".
                    format(attr, self.__attrs))
            self.stderr.write('\n')
        else:
            print('{}:\t\t{}'.format(attr, getattr(self, '_' + attr)))

    @shell.completer('get')
    def complete_get(self, cmd, args, text):
        if not args:
            return [ x for x in self.__attrs if x.startswith(text) ]

    @shell.command('create')
    def do_create(self, cmd, args):
        """\
        Use qemu-img to create disk image.
            create              Create the disk image if the file does not exist.
                                Overwrite existing file if any.
        """
        if not args:
            cmdlist = [
                    'qemu-img',
                    'create',
                    '-f',
                    self._format,
                    self._file,
                    self._size,
            ]
            cmdstr = subprocess.list2cmdline(cmdlist)
            print(cmdstr)
            subprocess.check_call(cmdlist)
        else:
            self.stderr.write("get: illegal argument '{}', must be one 'force'.")
            self.stderr.write('\n')

    @property
    def _file(self):
        return self._mode_stack[-1].args[0]

    @property
    def _is_cache_valid(self):
        """Check validity of cache by comparing the last modified time.

        If the disk image has been modified since this subshell is created,
        reset the last modified time and return False. Otherwise return True.

        The return value can be used to determine the validity of the cache.
        True = cache is valid, False = otherwise.

        TODO: The name of this method is not fully reflective what its function.
        """
        mtime = datetime.fromtimestamp(os.path.getmtime(self._file))
        if mtime == self.__mtime:
            return True
        else:
            self.__mtime = mtime
            return False

    @shell.command('ls')
    def do_ls(self, cmd, args):
        """\
        List information the disk image.
            ls dev              List devices, e.g., /dev/sda.
            ls fs               List mountable filesystems, e.g., /dev/sda1.
            ls part             List partitions, e.g., /dev/sda1.
        """
        if len(args) == 1 and args[0] in self.__ls_subcmd_map.keys():
            subcmd = args[0]
            self.__update_ls_cache(subcmd)
            print(self.__ls_cache[cache_key])
        else:
            self.stderr.write('ls: require 1 argument, must be one of {}.'
                    .format(sorted(self.__ls_subcmd_map.keys())))
            self.stderr.write('\n')

    def __update_ls_cache(self, subcmd):
            cache_key = 'ls-' + subcmd
            if not self.__ls_cache[cache_key] or not self._is_cache_valid:
                cmdlist = self._virt_cmd + self.__ls_subcmd_map[subcmd]
                self.__ls_cache[cache_key] = subprocess.check_output(cmdlist).decode()

    __ls_subcmd_map = {
            'dev': [ '--blkdevs' ],
            'fs': [ '--filesystems' ],
            'part': [ '--partitions' ],
    }
    @property
    def _virt_cmd(self):
        return [ 'sudo', 'virt-filesystems', '-a', self._file ]

    @shell.completer('ls')
    def complete_ls(self, cmd, args, text):
        if not args:
            return [ x for x in self.__ls_subcmd_map.keys() if x.startswith(text) ]

    @shell.command('mount')
    def do_mount(self, cmd, args):
        """\
        Mount a device or filesystem using guestmount.
        mount <fs> <mnt>    Mount a filesystem, <fs>, onto a mount point, <mnt>. The
                            <fs> must be one of the mountable filesystems, i.e., the
                            ones listed by `ls fs`.
        """
        if len(args) == 2:
            fs  = args[0]
            mnt = args[1]
            cmdlist = [ 'sudo', 'guestmount', '-o', 'allow_other',
                    '-a', self._file, '-m', fs, mnt, ]
            cmdstr = subprocess.list2cmdline(cmdlist)
            print(cmdstr)
            subprocess.check_call(cmdlist)
        else:
            self.stderr.write('mount: 2 arguments are required, {} are supplied'.
                    format(len(args)))
            self.stderr.write('\n')

    @shell.completer('mount')
    def complete_mount(self, cmd, args, text):
        if not args:
            self.__update_ls_cache('fs')
            rawlist = [ x.strip() for x in \
                    self.__ls_cache['ls-fs'].split('\n') if x ]
            return [ x for x in rawlist if x.startswith(text) ]
        elif len(args) == 1:
            return easycompleter.fs.find_matches(text)

    @shell.subshell(KpartxShell, 'part-raw')
    def do_kpartx(self, cmd, args):
        """\
        Partition and format the disk image using kpartx and mkfs tools.

        Usable only when format=raw.
        """
        if self._format == 'raw':
            if not args:
                return 'kpartx'
            else:
                self.stderr.write('part-raw: requires 0 argument, {} are supplied'.
                        format(len(args)))
                self.stderr.write('\n')
        else:
            self.stderr.write("kpartx: format '{}' is not 'raw'.".
                    format(self._format))
            self.stderr.write('\n')

    @shell.subshell(LibguestfsShell, 'part-all')
    def do_libguestfs(self, cmd, args):
        """\
        Partition and format the disk image using libguestfs.

        Usable for disk images of all formats.
        """
        if not args:
            return 'kpartx'
        else:
            self.stderr.write('part-all: requires 0 argument, {} are supplied'.
                    format(len(args)))
            self.stderr.write('\n')


class ZPartShell(shell.Shell):

    def preloop(self):
        print(textwrap.dedent('''\
                Welcome to zpart!
                zpart: Create, partition, format, and mount disk images with ease.

                Enter '?' followed by a tab to get help.
                '''))

    def postloop(self):
        print('Thanks for using zpart. Bye!')

    __pkgs = [
            'parted',
            'kpartx',
            'libguestfs-tools',
    ]
    @shell.command('install-tools')
    def do_install(self, cmd, args):
        """\
        Install tools that this shell uses.
            install-tools       sudo apt-get install <prerequisites>.
        """
        if not args:
            apt_cmd = ['sudo', 'apt-get', 'install', '--force-yes', '-y']
            yellow = colored.fg('yellow')
            reset = colored.attr('reset')

            cmdlist = apt_cmd + self.__pkgs
            print(subprocess.list2cmdline(cmdlist))
            print(yellow +
                "NOTE: If prompted to configure libguestfs-tools, choose YES." + reset)
            proc = subprocess.check_call(cmdlist)
            return
        else:
            self.stderr.write('install-tools: 0 argument is required, {} are supplied'.
                    format(len(args)))
            self.stderr.write('\n')

    @shell.subshell(ImageShell, 'image')
    def do_image(self, cmd, args):
        """\
        Select a disk image to work on.
            image <file>        Select the image to create/re-create, enter a subshell.
                                If <file> already exists, its format and size are read
                                using `qemu-img info`. If <file> does not exist, the
                                format and size of the image need to be set in the
                                subshell using the 'set' command.
        """
        if len(args) != 1:
            self.stderr.write('create: requires 1 argument, {} are supplied.'.
                    format(len(args)))
            self.stderr.write('\n')
            return
        image_name = args[0]
        return os.path.basename(image_name)

    @shell.completer('image')
    def complete_image(self, cmd, args, text):
        if not args:
            return easycompleter.fs.find_matches(text)

def __update_parser(parser):
    """Update the parser object for the shell.

    Arguments:
        parser: An instance of argparse.ArgumentParser.
    """
    def __stdin(s):
        if s is None:
            return None
        if s == '-':
            return sys.stdin
        return open(s, 'r', encoding = 'utf8')
    parser.add_argument('--root-prompt',
            metavar = 'STR',
            default = 'zpart',
            help = 'the prompt string of the root shell')
    parser.add_argument('--temp-dir',
            metavar = 'DIR',
            default = '/tmp/zpart-shell',
            help = 'the directory to save history files')
    parser.add_argument('file',
            metavar = 'FILE',
            nargs = '?',
            type = __stdin,
            help = "execute script in non-interactive mode. '-' = stdin")

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description = __doc__,
            formatter_class = argparse.ArgumentDefaultsHelpFormatter)
    __update_parser(parser)
    args = parser.parse_args()

    if args.file:
        ZPartShell(
                batch_mode = True,
                debug = False,
                root_prompt = 'zpart',
                temp_dir = args.temp_dir,
        ).batch_string(args.file.read())
    else:
        d = vars(args)
        del d['file']
        ZPartShell(**d).cmdloop()
