#!/usr/bin/env python3


import sys
import getpass
import paramiko
import re
import time
import json
from ucsmsdk.ucshandle import UcsHandle
from ucsmsdk.mometa.firmware.FirmwareDownloader import FirmwareDownloader
from ucsmsdk.mometa.firmware.FirmwareInfraPack import FirmwareInfraPack
from ucsmsdk.mometa.trig.TrigAbsWindow import TrigAbsWindow
from ucsmsdk.mometa.firmware.FirmwareAck import FirmwareAckConsts
from ucsmsdk.mometa.firmware.FirmwareComputeHostPack import FirmwareComputeHostPack
from threading import Thread
from urllib.error import URLError
from progress.spinner import Spinner
from colorama import Fore, Back, Style
from http.client import RemoteDisconnected

####### Import Metadata

with open('metadata') as f:
    data = f.read()

metadata = json.loads(data)

ssh_ip = metadata["ssh_ip"]
ssh_user = metadata["ssh_user"]
ssh_password = metadata["ssh_password"]

####### Functions

def ucs_connect(ucsm_ip, ucsm_user, ucsm_pass):
    ucs_handle = UcsHandle(ucsm_ip, ucsm_user, ucsm_pass)
    ucs_handle.login()
    return ucs_handle

def ucs_disconnect(ucs_handle):
    ucs_handle.logout()

def get_available_versions(ssh_ip, ssh_user, ssh_password):
    available_versions = []
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ssh_ip, username=ssh_user, password=ssh_password)
    stdin, stdout, stderr = client.exec_command('ls /isos/ucs')
    for line in stdout:
        line = line.strip('\n')
        line = re.search('\d\.\d\.\d[a-z]', line)
        if line is not None:
            available_versions.append(line.group(0))
    client.close()
    return available_versions

def get_available_files(ssh_ip, ssh_user, ssh_password, ucsm_version, ucs_fi_model, required_upgrades):
    available_files = {}
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ssh_ip, username=ssh_user, password=ssh_password)
    command = "ls /isos/ucs/"+ucsm_version
    stdin, stdout, stderr = client.exec_command(command)
    for line in stdout:
        line = line.strip('\n')
        if re.match('.*A.*', line) and re.match('.*'+ucs_fi_model+'.*', line) and 'infra' in required_upgrades:
            available_files['A']=line
        elif re.match('.*B.*', line) and 'server' in required_upgrades:
            available_files['B']=line
        elif re.match('.*C.*', line) and 'server' in required_upgrades:
            available_files['C']=line
    client.close()
    return available_files

def monitor_firmware_download(ucs_handle, file):
    timeout = 1800
    timepassed = 0
    while True:
        download_dn = "sys/fw-catalogue/dnld-"+file
        object = get_ucs_object_by_dn(ucs_handle, download_dn)
        fsm_progress = object.fsm_progr
        transfer_state = object.transfer_state
        if fsm_progress == "100" and transfer_state == "downloaded":
            return
        else:
            time.sleep(60)
            timepassed += 60
            if timepassed >= timeout:
                print ("timed out waiting for download of firmware bundle: "+file)
                sys.exit()

def get_ucs_object_by_dn(ucs_handle, dn):
    object = ucs_handle.query_dn(dn)
    return object

def convert_firmware_version(ucsm_version, bundle):
    pre = re.search('^\d\.\d', ucsm_version).group(0)
    post = re.search('\d[a-z]$', ucsm_version).group(0)
    bundle_version = pre+"("+post+")"+bundle
    return bundle_version

def console_spinner(delay=0.1):
    while True:
        for t in '|/-\\':
            sys.stdout.write(t)
            sys.stdout.flush()
            time.sleep(delay)
            sys.stdout.write('\b')
            if done:
                return

def get_rack_units(ucs_handle):
    rack_unit_objects = ucs_handle.query_classid("computeRackUnit")
    rack_units = []
    for rack_unit in rack_unit_objects:
        rack_unit = rack_unit.rn
        rack_units.append(rack_unit)
    return rack_units

def does_file_exist(ucs_handle, file):
    results = ucs_handle.query_classid('firmwareDownloader')
    file_list = []
    for result in results:
        file_list.append(result.file_name)
    if file in file_list:
        return True
    else:
        return False

####### Code

print ("")
print (Fore.GREEN+"NOTE: The following python script will upgrade both the infrastructure (\"A\") and server (\"B\" and \"C\") firmware on the target UCS domain to the desired firmware version. It will first check to make sure an upgrade is required, it will download the firmware that is required for both infrastructure and server firmware and then initate the required upgrades to get to the desired level. Firmware is downloaded from preconfigured remote repository via SCP. Currently the script will update all rack servers connected to the FIs."+Style.RESET_ALL)
print ("")

while True:
    ucsm_ip = input(Style.BRIGHT+Fore.WHITE+"Please enter the UCS Manager IP address: "+Style.RESET_ALL)
    ucsm_user = input(Style.BRIGHT+Fore.WHITE+"Please enter the UCS Manager username: "+Style.RESET_ALL+"[admin] ")
    if not ucsm_user:
        ucsm_user = "admin"
    ucsm_pass = getpass.getpass(Style.BRIGHT+Fore.WHITE+"Please enter the UCS Manager password: "+Style.RESET_ALL)
    try:
        ucs_handle = ucs_connect(ucsm_ip, ucsm_user, ucsm_pass)
        if ucs_handle:
            ucs_disconnect(ucs_handle)
            print ("   <> Successfully connected to UCS Manager.")
            print ("      "+u'\U0001F44D'+" Done.")
            print ("\n")
            break
    except:
        print ("   <> Unable to connect to UCS Mananger with the provided details, please retry...")

available_versions = get_available_versions(ssh_ip, ssh_user, ssh_password)

while True:
    print (Style.BRIGHT+Fore.WHITE+"The following are the available UCS firmware versions: "+Style.RESET_ALL)
    for each in available_versions:
        print ("   <> "+each)
    ucsm_version = input(Style.BRIGHT+Fore.WHITE+"Please enter the desired UCS firmware version : "+Style.RESET_ALL)
    if ucsm_version in available_versions:
        print ("   <> Found selected version!")
        print ("      "+u'\U0001F44D'+" Done.")
        print ("\n")
        break
    else:
        print ("   <> Can't find selected version, please retry...")

ucs_handle = ucs_connect(ucsm_ip, ucsm_user, ucsm_pass)

A_bundle_version = convert_firmware_version(ucsm_version, "A")
B_bundle_version = convert_firmware_version(ucsm_version, "B")
C_bundle_version = convert_firmware_version(ucsm_version, "C")


# Create list to capture required upgrades
required_upgrades = []

# Check if "A" bundle infrastructure firmware upgrade is required
firmware_status = ucs_handle.query_dn('sys/fw-status')
print (Style.BRIGHT+Fore.WHITE+"Checking whether infrastructure firmware upgrade required..."+Style.RESET_ALL)
print ("   <> Desired infrastructure firmware version: "+A_bundle_version)
print ("   <> Current infrastructure firmware version: "+firmware_status.package_version)
if firmware_status.package_version != A_bundle_version:
    print (Style.BRIGHT+Fore.WHITE+"   Infrastructure firmware upgrade required."+Style.RESET_ALL)
    required_upgrades.append('infra')
else:
    print (Style.BRIGHT+Fore.WHITE+"   Infrastructure firmware upgrade not required."+Style.RESET_ALL)
print ("      "+u'\U0001F44D'+" Done.")
print ("\n")

# Check if "B" and "C" bundle server firmware upgrades are required
rack_unit_firmware_status = []
rack_units = get_rack_units(ucs_handle)
print (Style.BRIGHT+Fore.WHITE+"Checking whether server firmware upgrade required..."+Style.RESET_ALL)
print ("   <> Desired server firmware version: "+C_bundle_version)
for rack_unit in rack_units:
    status = ucs_handle.query_dn('sys/'+rack_unit+'/fw-status').package_version
    status_list = status.split(",")
    for status_item in status_list:
        if status_item == C_bundle_version:
            print ("   <> "+rack_unit+" current firmware: "+status)
            rack_unit_firmware_status.append("no")
            break
        else:
            print ("   <> "+rack_unit+" current firmware: "+status)
            rack_unit_firmware_status.append("yes")


result = all(elem == "no" for elem in rack_unit_firmware_status)
if result:
    print (Style.BRIGHT+Fore.WHITE+"   Server firmware upgrade not required."+Style.RESET_ALL)
else:
    print (Style.BRIGHT+Fore.WHITE+"   Server firmware upgrade required."+Style.RESET_ALL)
    required_upgrades.append('server')
print ("      "+u'\U0001F44D'+" Done.")
print ("\n")


if 'infra' in required_upgrades or 'server' in required_upgrades:

    # Get fabric interconnect model type
    dn = "sys/switch-A"
    fi_object = ucs_handle.query_dn(dn)
    ucs_fi_model = re.sub('UCS-FI-', '', fi_object.model)
    print (Style.BRIGHT+Fore.WHITE+"Retrieving target Fabric Interconnect model type..."+Style.RESET_ALL)
    print ("   <> UCS FI model: "+ucs_fi_model)
    print ("      "+u'\U0001F44D'+" Done.")
    print ("\n")
    if re.match('64\d\d', ucs_fi_model):
        ucs_fi_model = "6400"
    elif re.match('63\d\d', ucs_fi_model):
        ucs_fi_model = "6300"
    elif re.match('62\d\d', ucs_fi_model):
        ucs_fi_model = "6200"


    # Create list to track required firmware downloads
    required_fimware_downloads = []


    # Get a list of available files from remote server
    available_files = get_available_files(ssh_ip, ssh_user, ssh_password, ucsm_version, ucs_fi_model, required_upgrades)
    print (Style.BRIGHT+Fore.WHITE+"Checking whether firmware needs to be downloaded to UCS..."+Style.RESET_ALL)



    # If infrastructure firmware upgrade required
    if 'infra' in required_upgrades:

        # Check if file already downloaded to UCS
        result = does_file_exist(ucs_handle, available_files['A'])

        # If file does not already exist in UCS
        if not result:

            # set as requried download
            required_fimware_downloads.append(available_files['A'])

            # Download infrastructure firmware file
            print ("   <> Downloading infrastructure firmware: "+available_files['A'])
            mo = FirmwareDownloader(parent_mo_or_dn="sys/fw-catalogue", file_name = available_files['A'], pwd=ssh_password, remote_path="/isos/ucs/"+ucsm_version, server=ssh_ip, user=ssh_user)
            ucs_handle.add_mo(mo)

            # Commit download
            ucs_handle.commit()

        else:
            print ("   <> Infrastructure firmware: "+available_files['A']+" already exists in UCS.")


    # If server firmware upgrade required
    if 'server' in required_upgrades:

        # Check if file already downloaded to UCS
        result = does_file_exist(ucs_handle, available_files['B'])

        # If file does not already exist in UCS
        if not result:

            # set as requried download
            required_fimware_downloads.append(available_files['B'])

            # Download "B" server firmware file
            print ("   <> Downloading \"B\" server firmware: "+available_files['B'])
            mo = FirmwareDownloader(parent_mo_or_dn="sys/fw-catalogue", file_name = available_files['B'], pwd=ssh_password, remote_path="/isos/ucs/"+ucsm_version, server=ssh_ip, user=ssh_user)
            ucs_handle.add_mo(mo)

        else:
            print ("   <> Server firmware: "+available_files['B']+" already exists in UCS.")

        # Check if file already downloaded to UCS
        result = does_file_exist(ucs_handle, available_files['C'])

        # If file does not already exist in UCS
        if not result:

            # set as requried download
            required_fimware_downloads.append(available_files['C'])

            # Download "C" server firmware file
            print ("   <> Downloading \"C\" server firmware: "+available_files['C'])
            mo = FirmwareDownloader(parent_mo_or_dn="sys/fw-catalogue", file_name = available_files['C'], pwd=ssh_password, remote_path="/isos/ucs/"+ucsm_version, server=ssh_ip, user=ssh_user)
            ucs_handle.add_mo(mo)

            # Commit downloads
            ucs_handle.commit()

        else:
            print ("   <> Server firmware: "+available_files['C']+" already exists in UCS.")

    if 'infra' in required_upgrades or 'server' in required_upgrades:

        # if any upgrades are required, get a list of available files from remote server
        result = not bool(required_fimware_downloads)
        if not result:

            # Start spinner indicator
            done = False
            spinner = Thread(target=console_spinner)
            print ("   <> Download(s) in progress...", end='')
            spinner.start()

            # Monitor status of downloads
            threads = []
            for file in required_fimware_downloads:
                thread = Thread(target=monitor_firmware_download, args=(ucs_handle, file,))
                threads.append(thread)
                thread.start()
            for thread in threads:
                thread.join()

            # Stop spinner indicator
            done = True

            print ("      "+u'\U0001F44D'+" Done.")
            print ("\n")

    else:
        print ("      "+u'\U0001F44D'+" Done.")
        print ("\n")


    # If infrastructure firmware upgrade required
    if 'infra' in required_upgrades:

        print (Style.BRIGHT+Fore.WHITE+"Starting Infrastructure firmware upgrade..."+Style.RESET_ALL)

        mo = FirmwareInfraPack(parent_mo_or_dn="org-root", infra_bundle_version=A_bundle_version, name="default")
        ucs_handle.add_mo(mo, True)
        mo = TrigAbsWindow(parent_mo_or_dn="sys/sched-infra-fw", name="infra-fw")
        ucs_handle.add_mo(mo, True)
        ucs_handle.commit()

        # Disconnect from UCSM
        ucs_disconnect(ucs_handle)

        done = False
        spinner = Thread(target=console_spinner)
        print ("   <> Infrastructure firmware upgrade in progress...", end='')
        spinner.start()

        timeout = 2400
        elapsed = 0

        while True:
            # Connect to UCSM
            try:
                ucs_handle = ucs_connect(ucsm_ip, ucsm_user, ucsm_pass)
            except (ConnectionRefusedError, URLError, TimeoutError, RemoteDisconnected):
                pass

            if ucs_handle.is_valid():
            # Check if FI reboot required and if so acknowledge reboot
                firmware_ack = ucs_handle.query_dn('sys/fw-system/ack')
                if firmware_ack.oper_state == 'waiting-for-user':
                    firmware_ack.adminState = FirmwareAckConsts.ADMIN_STATE_TRIGGER_IMMEDIATE
                    ucs_handle.set_mo(firmware_ack)
                    ucs_handle.commit()

                # Check running version against desired version
                else:
                    system_firmware_status = ucs_handle.query_dn('sys/fw-system')
                    firmware_status = ucs_handle.query_dn('sys/fw-status')
                    switchA_firmware_status = ucs_handle.query_dn('sys/switch-A/fw-status')
                    switchB_firmware_status = ucs_handle.query_dn('sys/switch-B/fw-status')
                    if system_firmware_status.oper_state == 'ready' and firmware_status.oper_state == 'ready' and firmware_status.package_version == A_bundle_version and switchA_firmware_status.oper_state == 'ready' and switchA_firmware_status.package_version == A_bundle_version and switchB_firmware_status.oper_state == 'ready' and switchB_firmware_status.package_version == A_bundle_version:
                        done = True
                        print ("")
                        print ("      "+u'\U0001F44D'+" Done.")
                        print ("\n")
                        break
                ucs_disconnect(ucs_handle)
            if elapsed > timeout:
                done = True
                print ("")
                sys.exit("Infrastructure firmware upgrade operation timed out!")
            time.sleep(60)
            elapsed += 60

    # If server firmware upgrade required
    if 'server' in required_upgrades:

        # Upgrade server firmware
        print (Style.BRIGHT+Fore.WHITE+"Starting \"B\" and \"C\" server firmware upgrades..."+Style.RESET_ALL)
        for rack_unit in rack_units:
            print ("   <> Upgrading server firmware on "+rack_unit)

        mo = FirmwareComputeHostPack(parent_mo_or_dn="org-root", blade_bundle_version=B_bundle_version, name="default", rack_bundle_version=C_bundle_version)
        ucs_handle.add_mo(mo, True)
        ucs_handle.commit()


        # Disconnect from UCSM
        ucs_disconnect(ucs_handle)

        done = False
        spinner = Thread(target=console_spinner)
        print ("   <> Server firmware upgrade(s) in progress...", end='')
        spinner.start()


        timeout = 1800
        elapsed = 0

        while True:
            # Connect to UCSM
            try:
                ucs_handle = ucs_connect(ucsm_ip, ucsm_user, ucsm_pass)
            except (ConnectionRefusedError, URLError, TimeoutError, RemoteDisconnected):
                pass

            if ucs_handle.is_valid():
                # Check running version against desired version
                firmware_status_list = []
                for rack_unit in rack_units:
                    firmware_status = ucs_handle.query_dn('sys/'+rack_unit+'/fw-status').oper_state
                    firmware_status_list.append(firmware_status)
                if 'upgrading' not in firmware_status_list:
                    done = True
                    print ("")
                    print ("      "+u'\U0001F44D'+" Done.")
                    print ("\n")
                    break
                else:
                    ucs_disconnect(ucs_handle)
                    if elapsed > timeout:
                        done = True
                        sys.exit("\"B\" and \"C\" server firmware upgrade operation timed out!")
            time.sleep(60)
            elapsed += 60

else:
    print (Style.BRIGHT+Fore.WHITE+"No upgrades required, firmware already at desired version!"+Style.RESET_ALL)
    print ("      "+u'\U0001F44D'+" Done.")
    print ("\n")
