"""Internal shell class for zpart."""

from datetime import datetime
import easycompleter
from easyshell import shell
import json
import os
import subprocess
import terminaltables
import textwrap
import time
import traceback


class PartedShell(shell.Shell):
    """Create partition table and partitions.

        mktbl               Create the partition table.
        mkpart              Create a partition.
        set                 Set flags for partitions.
        show                Display partition table and partitions, if any.
    """

    @property
    def _file(self):
        # Use the parent shell's _file property. This is bit of a hack.
        return self._mode_stack[-1].shell._file

    @shell.command('show', nargs = 0)
    def do_show(self, cmd, args):
        """Display the partition table.
        """
        data = self.__parse_tbl()
        if not data:
            print('Cannot parse image.')
            return

        if not data[0]:
            print('Cannot find partition table.')
            return

        print('fmt  =', data[0][0])
        print('size =', data[0][1])

        if len(data) <= 2:
            print('Cannot find partitions.')
            return

        table = terminaltables.AsciiTable(data[1:])
        print(table.table)

    def __parse_tbl(self):
        """Parse the output of `parted print -m`.

        Return a list of list:
            [
                [ size, format ],
                [ 'id', 'start', 'end', 'length', 'filesystem', 'type', flags' ],
                ( actual partition information goes here ... )
            ]

        If cannot parse the image, return None.
        If cannot find partition table, return [ [ size, format ] ].
        If cannot find partitions, return [ [size, format], ['id', ...] ].
        """
        # The -m option of the parted program outputs machine parsable outputs
        # such as the following:
        #           (some random shit that we do not care about here ...)
        #           BYT;
        #           /tmp/tmp.img:4295MB:file:512:512:gpt:;
        #           1:17.4kB:128MB:128MB::primary:boot;
        #           2:300MB:1000MB:700MB::logical:;
        #           3:1000MB:2000MB:999MB::logical:;
        #           4:2000MB:4294MB:2294MB::logical:;
        #           5:4294MB:4294MB:512B::logical:;
        cmdlist = self._parted_cmd + ['print', '-m']
        try:
            rawlines = subprocess.check_output(cmdlist).decode().rstrip('\n').split('\n')
        except subprocess.CalledProcessError:
            return

        i = 0
        for i in range(len(rawlines)):
            line = rawlines[i].strip()
            if line == 'BYT;':
                i += 1
                break

        # Hereafter, the value of i is is altered.
        if i >= len(rawlines):
            return

        title_line = rawlines[i].strip(';')
        toks = title_line.split(':')

        data = [ [toks[5], toks[1]] ]

        if i + 1 >= len(rawlines):
            return data

        data.append(['id', 'start', 'end', 'length', 'filesystem', 'type', 'flags'])
        for j in range(i + 1, len(rawlines)):
            line = rawlines[j].strip(';')
            datum = line.split(':')
            data.append(datum)

        return data

    __tbl_fmts = [ 'bsd', 'dvh', 'gpt', 'loop', 'mac', 'msdos', 'pc98', 'sun', ]
    @shell.command('mktbl', nargs = 1)
    def do_mktbl(self, cmd, args):
        """\
        Create parition tabel.

            mktbl <tbl_fmt>         Create partition table of format <tbl_fmt>,
                                    which can be one of the following:
                                            bsd   dvh   gpt   loop
                                            mac   msdos pc98  sun
                                    Rule of thumb: msdos for DOS, gpt for Linux.

        WARNING: This operation will erase all data on the disk image without prompting
        for confirmation.
        """
        fmt = args[0]
        if not fmt in self.__tbl_fmts:
            self.stderr.write("mktbl: '{}' is not one of {}\n".
                    format(fmt, self.__tbl_fmts))
            return

        self._run_parted_cmd(['mklabel', args[0]])

    @shell.completer('mktbl')
    def complete_mktbl(self, cmd, args, text):
        if not args:
            return [ x for x in self.__tbl_fmts if x.startswith(text) ]


    __mkpart_types = [ 'primary', 'logical', 'extended', ]
    @shell.command('mkpart', nargs = 3)
    def do_mkpart(self, cmd, args):
        """\
        Create a new partition.
            mkpart <type> <start> <end>

        <type> is one of the following:
            primary, logical, extended

        <start> and <end> are offsets. You can use k, M, G, T, and % (percent) as
        suffix. Without any suffix, the unit is byte. Note that here 1k = 1000, 1M =
        1000k, and so forth.

        Note that the actual starting and ending offsets of a partition might differ
        from the ones that are used to create the partition. This is due to alignment
        considerations.
        """
        type = args[0]
        if not type in self.__mkpart_types:
            self.stderr.write("mkpart: '{}' is not one of {}.\n".
                    format(type, self.__mkpart_types))
            return

        self._run_parted_cmd([ 'mkpart', type, args[1], args[2] ])

    @shell.completer('mkpart')
    def complete_mkpart(self, cmd, args, text):
        if not args:
            return [ x for x in self.__mkpart_types if x.startswith(text) ]

    __part_flags = [
            'boot',
            'root',
            'swap',
            'hidden',
            'raid',
            'lvm',
            'lba',
            'legacy_boot',
            'palo',
    ]
    @shell.command('set', nargs = 3)
    def do_set(self, cmd, args):
        """\
        Set flags for partitions.
            set <id> <flag> {on,off}    Set <flag> to on/off for the <id>-th partition.

        <id> must be one of the ids displayed by the 'show' command.

        <flag> must be one of the following (space separated):
                    boot root swap hidden raid lvm lba legacy_boot palo

        Certain flags are only applicable to a specific filesystem. Consult the man page
        of parted(8) for more information.

        To display flags for partitions, use the 'show' command.
        """
        id, flag, state = args

        ids = self._ids
        if not ids:
            self.stderr.write('set: no partition found.\n')
            return

        should_stop = False
        if not id in ids:
            self.stderr.write("set: '{}' is not one of {}.\n".
                    format(id, ids))
            should_stop = True

        if not flag in self.__part_flags:
            self.stderr.write("set: '{}' is not one of {}.\n".
                    format(flag, self.__part_flags))
            should_stop = True

        if not state in ['on','off']:
            self.stderr.write("set: '{}' is not one of ['on', 'off'].\n".
                    format(state))
            should_stop = True

        if should_stop:
            return

        self._run_parted_cmd(['set', id, flag, state])

    @property
    def _ids(self):
        """Get the ids of available partitions."""
        data = self.__parse_tbl()
        if not data or len(data) < 3:
            return
        else:
            return [ x[0] for x in data[2:] ]

    @shell.completer('set')
    def complete_set(self, cmd, args, text):
        if not args:
            ids = self._ids
            if ids:
                return [ x for x in ids if x.startswith(text) ]
        elif len(args) == 1:
            return [ x for x in self.__part_flags if x.startswith(text) ]
        elif len(args) == 2:
            return [ x for x in {'on', 'off'} if x.startswith(text) ]


    def _run_parted_cmd(self, cmdlist):
        cmdlist = self._parted_cmd + cmdlist
        cmdstr = subprocess.list2cmdline(cmdlist)
        print(cmdstr)
        subprocess.check_call(cmdlist)

    @property
    def _parted_cmd(self):
        return [ 'parted', self._file, '-s' ]


class ImageShell(shell.Shell):

    """Manage a disk image.

    create          Create disk image.
    get             Show attributes.
    guestfish       Invoke the libguestfs shell, guestfish.
    ls              Display devices/partitions/filesystems on the disk image.
    mount           Mount a filesystem from the disk image.
    parted          Partition. Only raw format can use it.
    set             Set attributes.
    umount          Umount a filesystem.
    """

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

    @shell.command('set', nargs = 2)
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
        attr = args[0]
        if not attr in self.__attrs:
            self.stderr.write("get: illegal argument '{}', must be one of {}.\n".
                    format(attr, self.__attrs))
        else:
            setattr(self, '_' + attr, args[1])

    @shell.completer('set')
    def complete_set(self, cmd, args, text):
        if not args:
            return [ x for x in self.__attrs if x.startswith(text) ]

        if len(args) == 1 and args[0] == 'format':
            return [ x for x in {'qcow2', 'raw'} if x.startswith(text) ]

    __attrs = [ 'file', 'format', 'size', ]
    @shell.command('get', nargs = '?')
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

        attr = args[0]
        if not attr in self.__attrs:
            self.stderr.write("get: illegal argument '{}', must be one of {}.\n".
                    format(attr, self.__attrs))
        else:
            print('{}:\t\t{}'.format(attr, getattr(self, '_' + attr)))

    @shell.completer('get')
    def complete_get(self, cmd, args, text):
        if not args:
            return [ x for x in self.__attrs if x.startswith(text) ]

    @shell.command('create', nargs = 0)
    def do_create(self, cmd, args):
        """\
        Use qemu-img to create disk image.
            create              Create the disk image if the file does not exist.
                                Overwrite existing file if any.
        """
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

    @shell.command('ls', nargs = 1)
    def do_ls(self, cmd, args):
        """\
        List information the disk image.
            ls dev              List devices, e.g., /dev/sda.
            ls fs               List mountable filesystems, e.g., /dev/sda1.
            ls part             List partitions, e.g., /dev/sda1.
        """
        if args[0] in self.__ls_subcmd_map.keys():
            subcmd = args[0]
            self.__update_ls_cache(subcmd)
            cache_key = 'ls-' + subcmd
            print(self.__ls_cache[cache_key])
        else:
            self.stderr.write('ls: {} is not one of {}.\n'
                    .format(args[0], sorted(self.__ls_subcmd_map.keys())))

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
        return [ 'virt-filesystems', '-a', self._file ]

    @shell.completer('ls')
    def complete_ls(self, cmd, args, text):
        if not args:
            return [ x for x in self.__ls_subcmd_map.keys() if x.startswith(text) ]

    @shell.command('mount', nargs = 2)
    def do_mount(self, cmd, args):
        """\
        Mount a device or filesystem using guestmount.
        mount <fs> <mnt>    Mount a filesystem, <fs>, onto a mount point, <mnt>. The
                            <fs> must be one of the mountable filesystems, i.e., the
                            ones listed by `ls fs`.
        """
        fs  = args[0]
        mnt = args[1]
        cmdlist = [ 'guestmount', '-o', 'allow_other',
                '-a', self._file, '-m', fs, mnt ]
        cmdstr = subprocess.list2cmdline(cmdlist)
        print(cmdstr)
        subprocess.check_call(cmdlist)

    @shell.command('umount', nargs = 1)
    def do_umount(self, cmd, args):
        """\
        Unmount a filesystem mounted via the 'mount' command.

        umount <mnt>        Unmount <mnt>.
        """
        mnt = args[0]
        if not os.path.isdir(mnt):
            self.stderr.write("umount: '{}' is not a directory.\n")
            return

        cmdlist = [ 'guestunmount', mnt ]
        cmdstr = subprocess.list2cmdline(cmdlist)
        print(cmdstr)
        subprocess.check_call(cmdlist)

    @shell.completer('umount')
    def complete_umount(self, cmd, args, text):
        if not args:
            return easycompleter.fs.find_matches(text)

    @shell.completer('mount')
    def complete_mount(self, cmd, args, text):
        if not args:
            self.__update_ls_cache('fs')
            rawlist = [ x.strip() for x in \
                    self.__ls_cache['ls-fs'].split('\n') if x ]
            return [ x for x in rawlist if x.startswith(text) ]
        elif len(args) == 1:
            return easycompleter.fs.find_matches(text)

    @shell.subshell(PartedShell, 'parted', nargs = 0)
    def do_parted(self, cmd, args):
        """\
        Partition and format the disk image using parted and mkfs tools.

        Usable only when format=raw.
        """
        if self._format == 'raw':
            return 'parted'
        else:
            self.stderr.write("parted: format '{}' is not 'raw'.\n".
                    format(self._format))

    @shell.command('guestfish', nargs = 0)
    def do_guestfish(self, cmd, args):
        """\
        Enter the libguestfs shell, guestfish to manage the disk image.

        Usable for disk images of all formats.
        """
        print(textwrap.dedent("""\
                Most useful commands in the guestfish shell:

                    To get detailed help message for a specific <cmd>:
                        help <cmd>

                    Start:
                        run

                    List devices/partitions/filesystems:
                        list-devices, list-partitions, list-filesystems

                    Zero a device:
                        zero
                        zero-device

                    Create and delete partitions, create the partition table:
                        part-init                           create partition table
                        part-add
                        part-del

                    Set attributes of partitions:
                        part-set-bootable
                        part-set-name

                    Create file systems:
                        mkfs, mkfs-b, mkfs-opts

                    Mount and unmount a filesystem:
                        mount, mount-ro, mount-loop, mount-options
                        umount, umount-all, umount-local, umount-opts

                    Change the local directory of guestfish itself:
                        lcd

                    Perform file operations on mounted filesystems:
                        cat <file>
                        chmod 0XXX <file>
                        chown <owner> <group> <file>
                        cp-a <src> <dst>                    cp -a <src> <dst>
                        df
                        df-h                                df -h
                        du
                        download <file> <host-file>
                        edit <file>                         Call $EDITOR to edit <file>
                        glob rm-f <path>/*                  rm -rf <path>/*
                        head <file>
                        head-n <num-lines> <file>
                        hexdump <file>
                        ln <target> <linkname>
                        ln-f <target> <linkname>            ln -f <target> <linkname>
                        ln-s <target> <linkname>            ln -s <target> <linkname>
                        ln-sf <target> <linkname>           ln -sf <target> <linkname>
                        ls <path>
                        ll <path>                           ls -al
                        mkdir <path>
                        mkdir-p <path>                      mkdir -p
                        mv <src> <dst>
                        rm <path>
                        rmdir <dir>
                        rm-rf <path>                        rm -rf <path>
                        read-file <file>
                        read-files <file> ...
                        readlink <path>
                        realpath <path>
                        tail <file>
                        tail-n <num-lines> <file>
                        touch <file>
                        truncate <file>
                        wc <file>
                        wc-c <file>                         wc -c <file>
                        wc-l <file>                         wc -l <file>
                        wc-w <file>                         wc -w <file>
                        write <file> <content>              cat <content> > <file>
                        write-append <file> <content>       cat <content> >> <file>

                    Raid related commands:
                        md-create
                        md-detail
                        md-stop
                """))
        subprocess.check_call([ 'guestfish', '-a', self._file ])
