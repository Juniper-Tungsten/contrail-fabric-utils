#!/usr/bin/python
"""
   Name : esxi_contrailvm.py
   Author : Prasad Miriyala, Kiran Desai
   Description : Start Contrail VM, utilities
                 1) Prepare .vmx
                 2) Creating networking support for contrail vm
                    a. create vswitches
                    b. port groups and vlans
                    c. uplink
                 3) Create ContrailVM
                    a. ssh to esxi server
                    b. ftp vmx, vmdk
                    d. create think vmdk
                    f. register contrail vm
                    g. power on
                 Utilities
                 4) Power on/off/reset
                 5) Unregister VM from VC, will be useful for modifying VM Parameters
"""

import cgitb
import paramiko
import os
import logging as LOG
try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict
import pdb
import socket

def ssh(host, user, passwd, log=LOG):
    """ SSH to any host.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if passwd:
        ssh.connect(host, username=user, password=passwd)
    else:
        ssh.connect(host, username=user, key_filename=env.keyfilenme)
    return ssh
# end ssh

def execute_cmd(session, cmd, log=LOG):
    """Executing long running commands in background has issues
    So implemeted this to execute the command.
    """
    log.debug("Executing command: %s" % cmd)
    stdin, stdout, stderr = session.exec_command(cmd)
# end execute_cmd

def execute_cmd_out(session, cmd, log=LOG):
    """Executing long running commands in background through fabric has issues
    So implemeted this to execute the command.
    """
    stdin, stdout, stderr = session.exec_command(cmd)
    out = None
    err = None
    out = stdout.read()
    err = stderr.read()
        #log.debug("STDERR: %s", err)
    return (out, err)
# end execute_cmd_out


class ContrailVM(object):
    """
    Create contrail VM
    """
    def __init__(self, vm_params):

        self.vm = vm_params['vm']
        self.vmdk = vm_params['vmdk']
        self.datastore = vm_params['datastore']
        self.eth0_mac = vm_params['eth0_mac']
        self.eth0_ip = vm_params['eth0_ip']
        self.eth0_pg = vm_params['eth0_pg']
        self.eth0_vswitch = vm_params['eth0_vswitch']
        self.eth0_vlan = vm_params['eth0_vlan']
        self.uplink_nic = vm_params['uplink_nic']
        self.uplink_vswitch = vm_params['uplink_vswitch']
        self.server = vm_params['server']
        self.username = vm_params['username']
        self.ntp_server = vm_params['ntp_server']
        self.password = vm_params['password']
        self.thindisk = vm_params['thindisk']
        self.vmdk_download_path = vm_params['vmdk_download_path']
	self.vm_domain = vm_params['domain']
        self.vm_id = 0
	self.vm_server = vm_params['vm_server']
	self.vm_password = vm_params['vm_password']
	self.vm_deb = vm_params['vm_deb']
        self._create_networking()
        print self._create_vm()
        print self._install_contrailvm_pkg(self.eth0_ip, "root", self.vm_password, self.vm_domain, self.vm_server, self.vm_deb)
        
    #end __init__    

    vmx_file = OrderedDict ((('.encoding', "UTF-8"),
                             ('config.version', "8"),
                             ('virtualHW.version', "8"),
                             ('vmci0.present', "TRUE"),
                             ('hpet0.present', "TRUE"),
                             ('nvram', "ContrailVM.nvram"),
                             ('pciBridge0.present', "TRUE"),
                             ('svga.present', "TRUE"),
                             ('pciBridge4.present', "TRUE"),
                             ('pciBridge4.virtualDev', "pcieRootPort"),
                             ('pciBridge4.functions' , "8"),
                             ('pciBridge5.present' , "TRUE"),
                             ('pciBridge5.virtualDev' , "pcieRootPort"),
                             ('pciBridge5.functions' , "8"),
                             ('pciBridge6.present' , "TRUE"),
                             ('pciBridge6.virtualDev' , "pcieRootPort"),
                             ('pciBridge6.functions' , "8"),
                             ('pciBridge7.present' , "TRUE"),
                             ('pciBridge7.virtualDev' , "pcieRootPort"),
                             ('pciBridge7.functions' , "8"),
                             ('virtualHW.productCompatibility', "hosted"),
                             ('powerType.powerOff', "soft"),
                             ('powerType.powerOn', "hard"),
                             ('powerType.suspend', "hard"),
                             ('powerType.reset', "soft"),
                             ('displayName', "sample"),
                             ('extendedConfigFile', "ContrailVM.vmxf"),
                             ('floppy0.present', "FALSE"),
                             ('numvcpus', "4"),
                             ('cpuid.coresPerSocket', "4"),
                             ('scsi0.present', "TRUE"),
                             ('scsi0.sharedBus', "none"),
                             ('scsi0.virtualDev', "lsilogic"),
                             ('memsize', "8228"),
                             ('scsi0:0.present', "TRUE"),
                             ('scsi0:0.fileName', "Contrail.vmdk"),
                             ('scsi0:0.deviceType', "scsi-hardDisk"),
                             ('ethernet0.present', "TRUE"),
                             ('ethernet0.virtualDev', "vmxnet3"),
                             ('ethernet0.networkName', "contrail-fab-pg"),
                             ('ethernet0.addressType', "static"),
                             ('ethernet0.address', "00:00:de:ad:be:ef"),
                             ('chipset.onlineStandby', "FALSE"),
                             ('guestOS', "ubuntu-64")))
    
    def _create_vmx_file(self, vmname, vmdkname, eth0mac=None, eth0pg=None, 
                         vswitch1=None, vswitch2=None, ):
        if vmname is not None:
            self.vmx_file['nvram'] = vmname + '.nvram'
            self.vmx_file['extendedConfigFile'] = vmname + '.vmxf'
            self.vmx_file['displayName'] = vmname
                
        if vmdkname is not None:
            self.vmx_file['scsi0:0.fileName'] = vmdkname + '.vmdk' 
                    
        if eth0mac is not None:
            self.vmx_file['ethernet0.address'] = eth0mac
                    
        if eth0pg is not None:
            self.vmx_file['ethernet0.networkName'] = eth0pg
                            

        vmf_fp = open("/tmp/contrail.vmx", "w+")

        for k, v in self.vmx_file.items():
            vmf_fp.write(k+ " = "+"\""+v+"\"\n")

        vmf_fp.close()
        return

    # end create_vmx_file

    def _create_vm(self):
        """
        Create vmx file and sftp to esxi host.
        Copies the thin vmdk and expands it.
        Register and power on contrail vm.
        """
        self._create_vmx_file(self.vm, self.vmdk, self.eth0_mac, self.eth0_pg)

        # open ssh session
        ssh_session = ssh(self.server, self.username, self.password)
        vm_store = self.datastore+"/"+self.vm+"/"
        get_vmid = 0
        print "Getting a list of all VMs, to check if contrailVM exists"
        get_vmid_cmd = ("vim-cmd vmsvc/getallvms | grep %s | awk \'{print $1}\'") % (self.vm)
        get_vmid, err = execute_cmd_out(ssh_session, get_vmid_cmd)
        if get_vmid is not 0:
            print "ContrailVM: %s, exists. Deleting and recreating" %(self.vm)
            out, err = execute_cmd_out(ssh_session, ("vim-cmd vmsvc/power.off %s") % (get_vmid))
            out, err = execute_cmd_out(ssh_session, ("vim-cmd vmsvc/unregister %s") % (get_vmid))
            out, err = execute_cmd_out(ssh_session, ("rm -rf %s") % (vm_store))

        create_dir = ("%s %s/%s") % ("mkdir -p", self.datastore, self.vm)
        execute_cmd_out(ssh_session, create_dir)
        # open sftp and transfer .vmx and thin disk and close the channel
        transport = paramiko.Transport((self.server, 22))
        transport.connect(username=self.username, password=self.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        dst_vmx = self.vm+".vmx"
        thin_vmdk = self.vmdk+"-disk.vmdk"
        thick_vmdk = self.vmdk+".vmdk"
        sftp.put("/tmp/contrail.vmx", vm_store+dst_vmx)
        try:
	    if self.thindisk is None:
                cmd = "wget "+self.vmdk_download_path+" -O /tmp/ContrailVM-disk1.vmdk"
                os.system('%s' %(cmd))
                self.thindisk = '/tmp/ContrailVM-disk1.vmdk'
       	    sftp.put(self.thindisk, vm_store+thin_vmdk)
	except Exception, e:
    		print '*** Caught exception: %s: %s' % (e.__class__, e)
                transport.close()
		return
        transport.close()
        
        # Convert thin to thick disk
        #vmkfstools -i "thin" -d zeroedthick "thick"
        src_vmdk = vm_store+thin_vmdk
        dst_vmdk = vm_store+thick_vmdk
        convert_thick_vmdk = ("vmkfstools -i \"%s\" -d zeroedthick \"%s\"") % (src_vmdk, dst_vmdk)
        print "Running:%s" %(convert_thick_vmdk)
        out, err = execute_cmd_out(ssh_session, convert_thick_vmdk)
        
        # Regiser the VM
        # vim-cmd solo/registervm <vmx file location>
        register_vm = "vim-cmd solo/registervm "+ vm_store + dst_vmx
        print "Running:%s" %(register_vm)
        register_out, register_err = execute_cmd_out(ssh_session, register_vm)
        if register_out:
            # Upon regisstration successful power on the VM
            try:
                self.vm_id = int(register_out)
                print "Powering on VM"
                power_on_vm = ("vim-cmd vmsvc/power.on %s") % (self.vm_id)
                power_on_out, power_on_err = execute_cmd_out(ssh_session, power_on_vm)
                if power_on_err:
                    # Check the error and unregister_vm
                    ssh_session.close()
                    return power_on_err
                elif power_on_out:
                    ssh_session.close()
                    return power_on_out
            except ValueError:
                ssh_session.close()
                return register_out
                None
                
        if register_err:
            # Close ssh session
            ssh_session.close()
            return register_err

        # Close ssh session
        ssh_session.close()
        
    # end _create_vm

    def _unregister_vm(self):
        # open ssh session
        ssh_session = ssh(self.server, self.username, self.password)
        unregister_vm_cmd = ("vim-cmd vmsvc/unregister %s") % (self.vm_id)
        out, err = execute_cmd_out(ssh_session, unregister_vm_cmd)
        ssh_session.close()
    # end _unregister_vm

    def _power_off_vm(self):
        # open ssh session
        ssh_session = ssh(self.server, self.username, self.password)
        power_off_vm_cmd = ("vim-cmd vmsvc/power.off %s") % (self.vm_id)
        out, err = execute_cmd_out(ssh_session, power_off_vm_cmd)
        ssh_session.close()
    # end _power_off_vm

    def _power_on_vm(self):
        # open ssh session
        ssh_session = ssh(self.server, self.username, self.password)
        power_on_vm_cmd = ("vim-cmd vmsvc/power.on %s") % (self.vm_id)
        out, err = execute_cmd_out(ssh_session, power_on_vm_cmd)
        ssh_session.close()
    # end _power_on_vm

    def _power_reset_vm(self):
        # open ssh session
        ssh_session = ssh(self.server, self.username, self.password)
        power_reset_vm_cmd = ("vim-cmd vmsvc/power.reset %s") % (self.vm_id)
        out, err = execute_cmd_out(ssh_session, power_reset_vm_cmd)
        ssh_session.close()
    # end _power_reset_vm

    def _create_networking(self):
        # open ssh session
        ssh_session = ssh(self.server, self.username, self.password)
        if ssh_session is None:
            return

        if self.eth0_vswitch is not 'vSwitch0':
            vswitch_cmd = ('esxcli network vswitch standard add --vswitch-name=%s') % (self.eth0_vswitch)
            print "Running:%s" %(vswitch_cmd)
            out, err = execute_cmd_out(ssh_session, vswitch_cmd)

        if self.eth0_pg is not None:
            pg_cmd = ('esxcli network vswitch standard portgroup add --portgroup-name=%s --vswitch-name=%s') % (
                self.eth0_pg, self.eth0_vswitch)
            print "Running:%s" %(pg_cmd)
            out, err = execute_cmd_out(ssh_session, pg_cmd)

        if self.eth0_vlan is not None and self.eth0_pg:
            vlan_cmd = ('esxcli network vswitch standard portgroup set --portgroup-name=%s --vlan-id=%s') % (
                self.eth0_pg, self.eth0_vlan)
            print "Running:%s" %(vlan_cmd)
            out, err = execute_cmd_out(ssh_session, vlan_cmd)

        if self.uplink_vswitch is not None:
            uplink_cmd = ('esxcli network vswitch standard uplink add --uplink-name=%s --vswitch-name=%s') % (
                self.uplink_nic, self.uplink_vswitch)
            print "Running:%s" %(uplink_cmd)
            out, err = execute_cmd_out(ssh_session, uplink_cmd)

        ssh_session.close()

    # end _create_networking

    def _install_contrailvm_pkg(self, ip, user, passwd, domain, server ,
                    pkg):
        MAX_RETRIES = 5
        retries = 0
        connected = False

        while retries <= MAX_RETRIES and connected == False:
            try:
                connected = True
                ssh_session = paramiko.SSHClient()
                ssh_session.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                print "Connecting to ContrailVM ip:%s" %(ip)
                if passwd:
                    ssh_session.connect(ip, username=user, password=passwd, timeout=300)
                else:
                    ssh.connect(host, username=user, key_filename=env.keyfilenme, timeout=300)
                sftp = ssh_session.open_sftp()
            except socket.error, paramiko.SSHException:
                connected = False
                ssh_session.close()
                retries = retries + 1
                continue

        if retries > MAX_RETRIES:
                return ( "Connection to %s failed" % (ip))


        sftp.put(pkg, "/tmp/contrail_pkg")
        sftp.close()

        #Set up ntp  
        print "Updating NTP settings on ContrailVM"
        ntp_cmd = ('ntpdate "%s"') %(self.ntp_server)
        out, err = execute_cmd_out(ssh_session, ntp_cmd)
        ntp_cmd = ('mv /etc/ntp.conf /etc/ntp.conf.orig')
        out, err = execute_cmd_out(ssh_session, ntp_cmd)
        ntp_cmd = ('touch /var/lib/ntp/drift')
        out, err = execute_cmd_out(ssh_session, ntp_cmd)
        ntp_cmd = ('echo "driftfile /var/lib/ntp/drift" >> /etc/ntp.conf')
        out, err = execute_cmd_out(ssh_session, ntp_cmd)
        ntp_cmd = ('echo "server %s" >> /etc/ntp.conf') % (self.ntp_server)
        out, err = execute_cmd_out(ssh_session, ntp_cmd)
        ntp_cmd = ('echo "restrict 127.0.0.1" >> /etc/ntp.conf')
        out, err = execute_cmd_out(ssh_session, ntp_cmd)
        ntp_cmd = ('echo "restrict -6 ::1" >> /etc/ntp.conf')
        out, err = execute_cmd_out(ssh_session, ntp_cmd)
        ntp_cmd = ('service ntp restart')
        out, err = execute_cmd_out(ssh_session, ntp_cmd)

        # end ntp setup
        print "Starting installation of contrail-setup package.."
        install_cmd = ("/usr/bin/dpkg -i %s") % ("/tmp/contrail_pkg")
        out, err = execute_cmd_out(ssh_session, install_cmd)
        setup_cmd = "/opt/contrail/contrail_packages/setup.sh"
        out, err = execute_cmd_out(ssh_session, setup_cmd)

        etc_host_cmd = ('echo "%s %s.%s %s" >> /etc/hosts') % (ip , server, domain, server)
        out, err = execute_cmd_out(ssh_session, etc_host_cmd)
        etc_host_cmd = ('echo "%s %s >> /etc/hosts') % (ip , server)
        out, err = execute_cmd_out(ssh_session, etc_host_cmd)


        # close ssh session
        ssh_session.close()
        print "Contrail package installed."

    # end _install_contrailvm_pkg
                         
#end class ContrailVM

'''
contrail_vm_params =  {  'vm':"ContrailVM",
                         'vmdk':"ContrailVM",
                         'datastore':"/vmfs/volumes/cs_shared/",
                         'eth0_mac':"00:00:00:aa:bb:cc",
                         'eth0_ip':"10.204.216.101",
                         'eth0_pg':"contrail-fab-pg",
                         'eth0_vswitch':'vSwitch0',
                         'eth0_vlan': None,
                         'uplink_nic': 'vmnic0',
                         'uplink_vswitch':'vSwitch0',
                         'server':"127.0.0.1",
                         'username':"root",
                         'password':"c0ntrail123",
                         'thindisk':"/tmp/ContrailVM-disk.vmdk",
			 'domain':'englab.juniper.net',
			 'smgr_ip':'10.204.217.59',
			 'vm_server': 'contrail-vm',
			 'vm_password': 'c0ntrail123',
			 'vm_deb': '~/contrail-install-packages_1.05-5440~havana_all.deb'
                      }

def main(args_str=None):
    ContrailVM(contrail_vm_params)    
# end main

if __name__ == '__main__':
    cgitb.enable(format='text')
    main()
'''
