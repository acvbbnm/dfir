"""Mount only the explicitly provisioned EBS volume; preserve existing filesystems."""
import json
import os
from pathlib import Path
import re
import subprocess


def select_disk(devices, volume_id, mountpoint):
    if not re.fullmatch(r'vol-[0-9a-f]{8,17}', volume_id):
        raise ValueError('A concrete EBS volume ID is required')
    serial = volume_id.replace('-', '')
    matches = [d for d in devices if str(d.get('serial', '')).replace('-', '') == serial]
    if len(matches) != 1:
        raise ValueError('Expected exactly one disk matching the EBS volume ID')
    disk = matches[0]
    if disk['type'] != 'disk' or disk.get('children'):
        raise ValueError('Refusing a partitioned/non-disk device')
    mounts = [m for m in disk.get('mountpoints', []) if m]
    if any(m != mountpoint for m in mounts):
        raise ValueError('Refusing a device mounted elsewhere, including the root disk')
    if disk.get('fstype') not in (None, '', 'ext4'):
        raise ValueError('Refusing an unexpected existing filesystem')
    name = disk['name']
    if not re.fullmatch(r'(nvme[0-9]+n[0-9]+|xvd[a-z]+)', name):
        raise ValueError('Unexpected block device name')
    return '/dev/' + name, bool(disk.get('fstype')), bool(mounts)


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout.strip()


def prepare(volume_id, mountpoint='/var/lib/elasticsearch', fstab='/etc/fstab', execute=run):
    devices = json.loads(execute('lsblk', '--json', '-o', 'NAME,TYPE,SERIAL,FSTYPE,MOUNTPOINTS'))['blockdevices']
    device, has_fs, mounted = select_disk(devices, volume_id, mountpoint)
    # Check the target before any format, even when the candidate disk is empty.
    def walk(items):
        for item in items:
            yield item
            yield from walk(item.get('children', []))
    for disk in walk(devices):
        if disk.get('name') != device.removeprefix('/dev/') and mountpoint in disk.get('mountpoints', []):
            raise ValueError('Mountpoint belongs to a different disk')
    if not mounted and Path(mountpoint).exists() and any(Path(mountpoint).iterdir()):
        raise ValueError('Refusing to hide existing data under a new mount')
    if not has_fs:
        signatures = json.loads(execute('wipefs', '--no-act', '--json', device)).get('signatures', [])
        if signatures:
            raise ValueError('Refusing to format a disk with unrecognized signatures')
        execute('mkfs.ext4', device)  # No force flag, never formats an existing filesystem.
    uuid = execute('blkid', '-s', 'UUID', '-o', 'value', device)
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', uuid):
        raise ValueError('Invalid filesystem UUID')
    entry = f'UUID={uuid} {mountpoint} ext4 defaults,nofail 0 2'
    path = Path(fstab)
    lines = path.read_text().splitlines()
    existing = [line for line in lines if line.strip() and not line.startswith('#') and len(line.split()) > 1 and line.split()[1] == mountpoint]
    if existing and existing != [entry]:
        raise ValueError('Conflicting fstab entry; operator review required')
    if not existing:
        with path.open('a') as stream:
            stream.write('\n' + entry + '\n')
    Path(mountpoint).mkdir(parents=True, exist_ok=True)
    if not mounted:
        execute('mount', mountpoint)


if __name__ == '__main__':
    prepare(os.environ['SOC_DATA_VOLUME_ID'])
