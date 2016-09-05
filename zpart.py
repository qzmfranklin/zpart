#!/usr/bin/env python3

import argparse
import colored
from easyshell import shell
import easycompleter
import os
import subprocess
import sys
import textwrap

from _image_shell import ImageShell


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
            self.stderr.write('install-tools: 0 argument is required, {} are supplied\n'.
                    format(len(args)))

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
            self.stderr.write('create: requires 1 argument, {} are supplied.\n'.
                    format(len(args)))
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
