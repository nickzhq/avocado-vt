"""
Base module for support lvm in qemu test;

For EmulatedLVM, no need any special configuration, lvm params will generate
automatically. Of course, customizable params is accept;
For real lvm partition, we need to specify some params, at lest, vg_name and
it's a real volume group on your host. If not, both pv_name and vg_name are
required and a new volumegroup will be created on device named pv_name, But
it will destroy data on your device and it's not recommended;

Required params:
    lv_name:
        lv_name like /dev/vg/lv; If not params["vg_name"]
        is required and if lv_name not set, use guest_name as
        lv_name; device mapper path (eg, /dev/mapper/vg-lv)
        doesn't support it now;
    lv_size
        string (eg, 30G) if not set image_size will be used;
    vg_name
        LogicalVolume group name, eg, "test_vg";
    pv_name
        PhysicalVolume name eg, /dev/sdb or /dev/sdb1;
"""

from __future__ import division

import logging
import math
import os
import re
import time

from avocado.core import exceptions
from avocado.utils import path, process

from virttest import data_dir, utils_misc

LOG = logging.getLogger("avocado." + __name__)

UNIT = "B"
COMMON_OPTS = "--noheading --nosuffix --unit=%s" % UNIT


def normalize_data_size(size):
    if re.match(".*\d$", str(size)):
        size = "%s%s" % (size, UNIT)
    size = float(utils_misc.normalize_data_size(size, UNIT, 1024))
    return int(math.ceil(size))


def cmd_output(cmd, res="[\w/]+"):
    result = process.run(cmd, ignore_status=True)
    if result.exit_status != 0:
        LOG.warning(result)
        return None
    output = result.stdout_text
    for line in output.splitlines():
        val = re.findall(res, line)
        if val:
            return val[0]
    return None


class Volume(object):
    def __init__(self, name, size):
        self.name = name
        self.path = name
        self.size = normalize_data_size(size)

    def get_attr(self, cmd, attr, res="[\w/]+"):
        """
        Get attribute of volume, if not found return None;

        :param cmd: command used to display volume info;
        :param attr: attribute name of the volume;
        :param res: regular expression to reading the attribute;
        :return: string or None
        """
        if attr:
            return cmd_output(cmd, res)
        return None

    def exists(self):
        """
        Check is the volume really exists or not;
        """
        return os.path.exists(self.path)

    def umount(self, extra_args="-f"):
        """
        Unmount volume;
        """
        if self.exists():
            cmd = "umount %s" % extra_args
            fd = open("/proc/mounts", "r")
            mount_list = fd.readlines()
            fd.close()
            for line in mount_list:
                dev, mount_point = line.split()[0], line.split()[2]
                if os.path.exists(dev) and os.path.samefile(dev, self.path):
                    process.system("%s %s" % (cmd, mount_point))


class PhysicalVolume(Volume):
    def __init__(self, name, size):
        super(PhysicalVolume, self).__init__(name, size)
        self.vg = None

    def create(self, extra_args="-ff --yes"):
        """
        Create physical volume on specify physical volume;

        :param extra_args: extra arguments for pvcreate command;
        :raise: CmdError or TestError;
        :return: physical volume abspath
        """
        if not self.exists():
            raise exceptions.TestError("Physical device not found")
        self.umount()
        cmd = "pvcreate %s %s" % (extra_args, self.name)
        process.system(cmd)
        LOG.info("Create physical volume: %s", self.name)
        return self.path

    def remove(self, extra_args=" -ff --yes"):
        """
        Remove a physical volume

        :param extra_args: extra arguments for ``pvremove`` command
        :raise: CmdError
        """
        cmd = "lvm pvremove %s %s" % (extra_args, self.name)
        process.system(cmd)
        LOG.info("logical physical volume (%s) removed", self.name)

    def resize(self, size, extra_args="-ff --yes"):
        """
        Resize a physical volume;

        :param size: new size of the physical volume device;
        :param extra_args: extra arguments for pvresize command;
        """
        size = int(math.ceil(normalize_data_size(size)))
        cmd = "lvm pvresize %s --setphysicalvolumesize=%s%s %s" % (
            extra_args,
            size,
            UNIT,
            self.name,
        )
        process.system(cmd)
        self.size = size
        LOG.info("resize volume %s to %s B" % (self.name, self.size))

    def display(self):
        """
        Show physical volume details

        :raise: CmdError
        """
        cmd = "pvdisplay %s" % self.name
        process.system(cmd)

    def get_attr(self, attr):
        """
        Get attribute of physical volume, if not found return None;

        :param attr: attribute name of the volume;
        :return: string or None
        """
        cmd = "lvm pvs -o %s %s %s" % (attr, COMMON_OPTS, self.name)
        return super(PhysicalVolume, self).get_attr(cmd, attr)

    def set_vg(self, vg):
        """
        Set VolumeGroup of the physical volume device;

        :param vg: VolumeGroup object
        """
        if isinstance(vg, VolumeGroup):
            self.vg = vg


class VolumeGroup(object):
    def __init__(self, name, size, pvs):
        self.name = name
        self.size = normalize_data_size(size)
        self.pvs = pvs
        self.lvs = []

    def create(self, extra_args="-ff --yes"):
        """
        Create volume group with specify physical volumes;

        :param extra_args: extra arguments for lvm command;
        :raise: CmdError or TestError;
        :return: volume group name;
        """
        cmd = "lvm vgcreate  %s %s" % (extra_args, self.name)
        for pv in self.pvs:
            if pv.vg and pv.vg.name != self.name:
                try:
                    pv.vg.reduce_pv(pv)
                except Exception:
                    pv.vg.remove()
            cmd += " %s" % pv.name
        process.system(cmd)
        LOG.info("Create new volumegroup %s", self.name)
        return self.name

    def remove(self, extra_args="-ff --yes"):
        """
        Remove the VolumeGroup;

        :param extra_args: extra arguments for lvm command;
        """
        cmd = "lvm vgremove %s %s" % (extra_args, self.name)
        process.system(cmd)
        LOG.info("logical volume-group(%s) removed", self.name)

    def get_attr(self, attr):
        """
        Get VolumeGroup attribute;

        :param attr: attribute name;
        :return: string or None;
        """
        cmd = "lvm vgs -o %s %s %s" % (attr, COMMON_OPTS, self.name)
        return cmd_output(cmd)

    def append_lv(self, lv):
        """
        Collect Logical Volumes on the VolumeGroup;

        :param lv: LogicalVolume Object
        """
        if isinstance(lv, LogicalVolume):
            if lv not in self.lvs:
                self.lvs.append(lv)

    def reduce_pv(self, pv, extra_args="-ff --yes"):
        """
        Reduce a PhysicalVolume from VolumeGroup;

        :param pv: PhysicalVolume object;
        :param extra_args: extra arguments pass to lvm command;
        """
        if not isinstance(pv, PhysicalVolume):
            raise TypeError("Need a PhysicalVolume object")
        cmd = "lvm vgreduce %s %s %s" % (extra_args, self.name, pv.name)
        process.system(cmd)
        self.pvs.remove(pv)
        LOG.info("reduce volume %s from volume group %s" % (pv.name, self.name))

    def extend_pv(self, pv, extra_args=""):
        """
        Add PhysicalVolume into VolumeGroup;

        :param pv: PhysicalVolume object
        :param extra_args: extra arguments used for vgextend command
        """
        if not isinstance(pv, PhysicalVolume):
            raise TypeError("Need a PhysicalVolume object")
        cmd = "lvm vgextend %s %s" % (self.name, pv.name)
        process.system(cmd)
        self.pvs.append(pv)
        LOG.info("add volume %s to volumegroup %s" % (pv.name, self.name))

    def exists(self):
        """
        Check VolumeGroup exists or not;

        :return: bool type, if exists True else False;
        """
        vg_name = self.get_attr("vg_name")
        return bool(vg_name)


class LogicalVolume(Volume):
    def __init__(self, name, size, vg, lv_extra_options=None):
        super(LogicalVolume, self).__init__(name, size)
        self.vg = vg
        self.path = os.path.join("/dev", vg.name, name)
        self.lv_extra_options = lv_extra_options

    def create(self):
        """
        Create LogicalVolume device;

        :return: path of logical volume;
        """
        vg_name = self.vg.name
        cmd = "lvm lvcreate -L %s%s -n %s %s" % (self.size, UNIT, self.name, vg_name)
        if self.lv_extra_options:
            cmd += " %s" % self.lv_extra_options
        process.system(cmd)
        LOG.info("create logical volume %s", self.path)
        return self.get_attr("lv_path")

    def remove(self, extra_args="-ff --yes", timeout=300):
        """
        Remove LogicalVolume device;

        :param extra_args: extra arguments pass to lvm command;
        :param timeout: timeout in seconds;
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            self.umount()
            cmd = "lvm lvremove %s %s/%s" % (extra_args, self.vg.name, self.name)
            status = process.system(cmd, ignore_status=True)
            if status == 0:
                LOG.info("logical volume(%s) removed", self.name)
                break
            time.sleep(0.5)

    def resize(self, size, extra_args="-ff"):
        """
        Resize LogicalVolume to new size;

        :param size: new size of logical volume;
        :param extra_args: extra arguments pass to lvm command;
        :return: size of logical volume;
        """
        path = self.get_attr("lv_path")
        size = str(size)
        if size.startswith("+"):
            size = self.size + normalize_data_size(size[1:])
        elif size.startswith("-"):
            size = self.size - normalize_data_size(size[1:])
        else:
            size = normalize_data_size(size)
        cmd = "lvm lvresize -n -L %s%s %s %s" % (size, UNIT, path, extra_args)
        process.system(cmd)
        self.size = size
        LOG.info("resize logical volume %s size to %s" % (self.path, self.size))
        return size

    def display(self, extra_args=""):
        """
        Shown logical volume details, warper of lvm command lvdisplay;

        :extra_args: extra arguments pass to lvdisplay command;
        :raise: CmdError when command exit code not equal 0;
        """
        path = self.get_attr("lv_path")
        cmd = "lvm lvs %s %s" % (extra_args, path)
        return process.system(cmd)

    def get_attr(self, attr):
        """
        Get logical volume attributes if not found return None;

        :param attr: attribute name;
        :return: attribute value string or None;
        :raise: CmdError when command exit code not equal 0;
        """
        cmd = "lvm lvs -o %s %s %s" % (attr, COMMON_OPTS, self.path)
        return super(LogicalVolume, self).get_attr(cmd, attr)


class LVM(object):
    def __init__(self, params):
        path.find_command("lvm")
        self.params = self.__format_params(params)
        self.pvs = self.__reload_pvs()
        self.vgs = self.__reload_vgs()
        self.lvs = self.__reload_lvs()
        self.trash = []

    def generate_id(self, params):
        """
        Create prefix with image_name;
        """
        black_str = re.compile(r"[-./]")
        return black_str.sub("_", os.path.basename(params["image_name"]))

    def __format_params(self, params):
        """
        Reformat test params;

        :param params: dict of test params;
        :return: dict of test params;
        """
        lv_size = params.get("lv_size")
        if lv_size is None:
            lv_size = params["image_size"]
        params["lv_size"] = normalize_data_size(lv_size)

        lv_name = params.get("lv_name")
        if lv_name is None:
            lv_name = "lv_%s" % self.generate_id(params)
            params["lv_name"] = lv_name

        vg_name = params.get("vg_name")
        if vg_name is None:
            vg_name = "vg_%s" % self.generate_id(params)
            params["vg_name"] = vg_name
        if lv_name.startswith("/dev"):
            if "mapper" not in lv_name:
                match = re.search("/dev/([\w_]+)/([\w_]+)", lv_name)
                vg_name, lv_name = [x[1:] for x in match.groups()]
                params["lv_name"] = lv_name
                params["vg_name"] = vg_name
        return params

    def register(self, vol):
        """
        Register new volume;

        :param vol: Volume object or VolumeGroup objects
        """
        if isinstance(vol, Volume) or isinstance(vol, VolumeGroup):
            self.trash.append(vol)
            LOG.info("Install new volume %s", vol.name)

    def unregister(self, vol):
        """
        Unregister volume or VolumeGroup;

        :param vol: Volume object or VolumeGroup objects
        """
        if vol in self.trash:
            self.trash.remove(vol)
            LOG.info("Uninstall volume %s", vol.name)

    def __reload_lvs(self):
        """
        Create LogicalVolume objects for exist Logical volumes;

        :return: list of Volume object
        """
        lvs = []
        cmd = "lvm lvs -o lv_name,lv_size,vg_name %s" % COMMON_OPTS
        output = process.run(cmd).stdout_text
        for line in output.splitlines():
            lv_name, lv_size, vg_name = line.split()
            vg = self.get_vol(vg_name, "vgs")
            lv = LogicalVolume(lv_name, lv_size, vg)
            vg.append_lv(lv)
            lvs.append(lv)
        return lvs

    def __reload_vgs(self):
        """
        Create VolumeGroup objects for exist volumegroups;

        :return: list of Volume object
        """
        vgs = []
        cmd = "lvm vgs -opv_name,vg_name,vg_size %s" % COMMON_OPTS
        output = process.run(cmd).stdout_text
        for line in output.splitlines():
            pv_name, vg_name, vg_size = line.split()
            pv = self.get_vol(pv_name, "pvs")
            vg = VolumeGroup(vg_name, vg_size, [pv])
            pv.set_vg(vg)
            vgs.append(vg)
        return vgs

    def __reload_pvs(self):
        """
        Create PhysicalVolume objects for exist physical volumes;

        :return: list of Volume object
        """
        pvs = []
        cmd = "lvm pvs -opv_name,pv_size %s" % COMMON_OPTS
        output = process.run(cmd).stdout_text
        for line in output.splitlines():
            pv_name, pv_size = line.split()
            pv = PhysicalVolume(pv_name, pv_size)
            pvs.append(pv)
        return pvs

    def get_vol(self, vname, vtype):
        """
        Get a exists volume object;

        :param vname: volume name;
        :param vtype: volume type eg, 'pvs', 'vgs', 'lvs';
        :return: Volume object or None;
        """
        if vtype:
            vols = getattr(self, vtype)
            for vol in vols:
                if vol.name == vname:
                    return vol
        return None

    def setup_pv(self, vg):
        """
        Create a physical volume devices;

        :param params["pv_name"]: Physical volume devices path or mount point;
        :param vg: VolumeGroup object;
        :return: list of PhysicalVolume object;
        """
        pvs = []
        for pv_name in self.params["pv_name"].split():
            pv = self.get_vol(pv_name, "pvs")
            if pv is None:
                pv = PhysicalVolume(pv_name, 0)
                pv.create()
                self.register(pv)
                self.pvs.append(pv)
            pv.set_vg(vg)
            pvs.append(pv)
        return pvs

    def setup_vg(self, lv):
        """
        Setup logical volumegroup which specify on volumegroup specify by
        params["vg_name"];

        :param params["vg_name"]: volumegroup name;
        :return: volumegroup object;
        """
        vg_name = self.params["vg_name"]
        vg = self.get_vol(vg_name, "vgs")
        if vg is None:
            pvs = self.setup_pv(vg)
            vg = VolumeGroup(vg_name, 0, pvs)
            vg.create()
            self.register(vg)
            for pv in pvs:
                pv.set_vg(vg)
            self.vgs.append(vg)
        else:
            LOG.info("VolumeGroup(%s) really exists" % vg_name + "skip to create it")
            pv_name = self.params["pv_name"].split()[0]
            pv = self.get_vol(pv_name, "pvs")
            if pv and pv.vg is vg:
                vg.append_lv(lv)
                return vg
            # if set pv_name then add pvs into volume group
            pvs = self.setup_pv(vg)
            for pv in pvs:
                vg.extend_pv(pv)
        vg.append_lv(lv)
        return vg

    def setup_lv(self):
        """
        Setup a logical volume, if a exist logical volume resize it
        else then create it on specify volumegroup;

        :param params["lv_name"]: logical volume name;
        :param params["lv_name"]: logical volume size;
        :return: logical volume object;
        """
        lv_name = self.params["lv_name"]
        lv_size = self.params["lv_size"]
        lv_extra_options = self.params.get("lv_extra_options")
        lv = self.get_vol(lv_name, "lvs")
        # Check is it a exist lv if exist return the volume object
        # else then create it;
        if lv is None:
            vg = self.setup_vg(lv)
            lv = LogicalVolume(lv_name, lv_size, vg, lv_extra_options)
            lv.create()
            self.register(lv)
            self.lvs.append(lv)
        else:
            LOG.info("LogicalVolume(%s) really exists " % lv_name + "skip to create it")
        if lv.size != lv_size:
            lv.display()
            LOG.warning(
                "lv size(%s) mismath," % lv.size + "required size %s;" % lv_size
            )
            lv.resize(lv_size)
        return lv

    def setup(self):
        """
        Main function to setup a lvm environments;

        :return: LogicalVolume path
        """
        self.rescan()
        lv = self.setup_lv()
        return lv.get_attr("lv_path")

    def cleanup(self):
        """
        Remove useless lv, vg and pv then reload lvm releated service;
        """
        if self.params.get("force_remove_image", "no") == "yes":
            self.trash.reverse()
            trash = self.trash[:]
            for vol in trash:
                if isinstance(vol, LogicalVolume):
                    vol.umount()
                if isinstance(vol, PhysicalVolume):
                    vg = vol.vg
                    if vg is not None:
                        vg.reduce_pv(vol)
                if isinstance(vol, VolumeGroup):
                    for pv in self.pvs:
                        if pv.vg is vol:
                            pv.vg = None
                vol.remove()
                self.unregister(vol)
        self.rescan()

    def rescan(self):
        """
        Rescan lvm , used before create volume or after remove volumes;
        """
        lvm_reload_cmd = self.params.get("lvm_reload_cmd")
        if lvm_reload_cmd:
            process.system(lvm_reload_cmd, ignore_status=True)
            LOG.info("reload lvm monitor service")


class EmulatedLVM(LVM):
    def __init__(self, params, root_dir=data_dir.get_tmp_dir()):
        path.find_command("losetup")
        path.find_command("dd")
        super(EmulatedLVM, self).__init__(params)
        self.data_dir = root_dir

    def get_emulate_image_name(self):
        img_path = self.params.get("emulated_image")
        if img_path is None:
            img_path = self.generate_id(self.params)
        return utils_misc.get_path(self.data_dir, img_path)

    def make_emulate_image(self):
        """
        Create emulate image via dd with 8M block size;
        """
        img_size = self.params["lv_size"]
        img_path = self.get_emulate_image_name()
        bs_size = normalize_data_size("8M")
        count = int(math.ceil(img_size / bs_size)) + 8
        LOG.info("create emulated image file(%s)" % img_path)
        cmd = "dd if=/dev/zero of=%s bs=8M count=%s" % (img_path, count)
        process.system(cmd)
        self.params["pv_size"] = count * bs_size
        return img_path

    def make_volume(self, img_file, extra_args=""):
        """
        Map a file to loop back device;

        :param img_file: image file path;
        :return: loop back device name;
        """
        cmd = "losetup %s --show --find %s" % (extra_args, img_file)
        pv_name = process.run(cmd).stdout_text.strip()
        self.params["pv_name"] = pv_name
        return pv_name

    def setup_pv(self, vg):
        """
        Setup physical volume device if exists return it directly;
        """
        pvs = []
        emulate_image_file = self.get_emulate_image_name()
        cmd = "losetup -j %s" % emulate_image_file
        output = process.run(cmd).stdout_text
        try:
            pv_name = re.findall("(/dev/loop\d+)", output, re.M | re.I)[-1]
            pv = self.get_vol(pv_name, "pvs")
        except IndexError:
            pv = None
        if pv is None:
            img_file = self.make_emulate_image()
            pv_name = self.make_volume(img_file)
            pv_size = self.params["pv_size"]
            pv = PhysicalVolume(pv_name, pv_size)
            pv.create()
            self.register(pv)
            self.pvs.append(pv)
        else:
            LOG.warning(
                "PhysicalVolume(%s) really exists" % pv_name + "skip to create it"
            )
        pv.set_vg(vg)
        pvs.append(pv)
        return pvs

    def setup(self):
        """
        Main function to setup a lvm environments;

        :return: LogicalVolume path
        """
        self.rescan()
        lv = self.setup_lv()
        if "/dev/loop" not in lv.get_attr("devices"):
            lv.display()
            raise exceptions.TestError(
                "logical volume exists but is not a " + "emulated logical device"
            )
        return lv.get_attr("lv_path")

    def cleanup(self):
        """
        Cleanup created logical volumes;
        """
        super(EmulatedLVM, self).cleanup()
        if self.params.get("remove_emulated_image", "no") == "yes":
            emulate_image_file = self.get_emulate_image_name()
            cmd = "losetup -j %s" % emulate_image_file
            output = process.run(cmd).stdout_text
            devices = re.findall("(/dev/loop\d+)", output, re.M | re.I)
            for dev in devices:
                cmd = "losetup -d %s" % dev
                LOG.info("disconnect %s", dev)
                process.system(cmd, ignore_status=True)
            emulate_image_file = self.get_emulate_image_name()
            cmd = "rm -f %s" % emulate_image_file
            process.system(cmd, ignore_status=True)
            LOG.info("remove emulate image file %s", emulate_image_file)
