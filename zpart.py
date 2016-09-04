#!/usr/bin/env python3

import argparse
import colored
from easyshell import shell
import easycompleter
import json
import os
import subprocess
import textwrap
import time
import traceback


class ImageShell(shell.Shell):

    def __init__(self, *args, **kwargs):
        super(ImageShell, self).__init__(*args, **kwargs)
        self._format = None
        self._size = None
        self.__update_attrs_by_fname(self._file)

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
            self.__create()
            return
        else:
            self.stderr.write("get: illegal argument '{}', must be one 'force'.")
            self.stderr.write('\n')

    def __create(self):
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
        try:
            subprocess.check_call(cmdlist)
        finally:
            pass


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
            image <image>       Select the image by filename, enter a subshell with it.
        """
        if len(args) != 1:
            self.stderr.write('image: requires 1 argument, {} are supplied.'.
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
