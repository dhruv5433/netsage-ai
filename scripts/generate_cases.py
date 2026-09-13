#!/usr/bin/env python3
"""
Generates data/cases.csv — the 30+ required troubleshooting cases for NetSage AI.
Run: python3 scripts/generate_cases.py
"""
import csv
import os

CASES = [
    # id, category, symptom, topology_note, show_output, expected_fault, osi_layer, concept_tag, severity
    dict(
        id="C001", category="VLAN",
        symptom="PC1 in VLAN 10 cannot ping PC2 also in VLAN 10, but both get correct IPs from DHCP.",
        topology="PC1 and PC2 connect to SW1 access ports Fa0/2 and Fa0/4. Both should be in VLAN 10.",
        show_output="SW1# show vlan brief\nVLAN Name    Status  Ports\n10  Sales    active  Fa0/2\n20  Guest    active  Fa0/4",
        expected_fault="Fa0/4 was assigned to VLAN 20 instead of VLAN 10 (wrong access VLAN on port).",
        osi_layer="Layer 2", concept="VLAN misconfiguration", severity="Medium",
    ),
    dict(
        id="C002", category="VLAN",
        symptom="Two PCs in different rooms, same VLAN, can't reach each other across two switches.",
        topology="SW1---trunk---SW2. PC1 on SW1 Fa0/2 (VLAN 10), PC2 on SW2 Fa0/6 (VLAN 10).",
        show_output="SW1# show interfaces trunk\nPort  Mode  Encapsulation  Status  Native vlan\nGi0/1 on    802.1q    trunking  1\nSW1# show interfaces trunk (allowed vlans)\nGi0/1  1-9,11-4094",
        expected_fault="VLAN 10 is pruned from the trunk's allowed VLAN list (switchport trunk allowed vlan excludes 10).",
        osi_layer="Layer 2", concept="Trunk allowed-VLAN misconfiguration", severity="High",
    ),
    dict(
        id="C003", category="VLAN",
        symptom="New PC plugged into an access port gets no DHCP address and cannot ping the gateway.",
        topology="PC3 connects to SW1 Fa0/8, intended for VLAN 30 (Engineering).",
        show_output="SW1# show running-config interface fa0/8\ninterface FastEthernet0/8\n switchport mode access\n (no switchport access vlan command present)",
        expected_fault="Port left in default VLAN 1 instead of VLAN 30; no DHCP scope exists for VLAN 1 on this network.",
        osi_layer="Layer 2", concept="Missing VLAN assignment", severity="Medium",
    ),
    dict(
        id="C004", category="Gateway",
        symptom="PC gets a valid IP via DHCP but cannot ping anything outside its own subnet, including the router.",
        topology="PC4 (VLAN 10, 192.168.10.0/24) with SVI Gi0/0/0.10 as gateway on R1.",
        show_output="PC4> ipconfig\nIP: 192.168.10.55  Mask: 255.255.255.0  Gateway: 192.168.20.1",
        expected_fault="DHCP pool default-router is set to the wrong subnet's gateway (192.168.20.1 instead of 192.168.10.1).",
        osi_layer="Layer 3", concept="Default gateway / DHCP scope mismatch", severity="High",
    ),
    dict(
        id="C005", category="Gateway",
        symptom="PC has correct IP and correct gateway address configured, but ping to gateway times out.",
        topology="PC5 statically configured 192.168.30.10/24, gateway 192.168.30.1 on R1 sub-interface Gi0/1.10.",
        show_output="R1# show ip interface brief\nGigabitEthernet0/1.10  192.168.30.1  YES manual administratively down  down",
        expected_fault="Router sub-interface is administratively shut down.",
        osi_layer="Layer 1/2", concept="Interface down (shutdown)", severity="High",
    ),
    dict(
        id="C006", category="DHCP",
        symptom="Multiple PCs in VLAN 40 fail to get an IP address; DHCP requests time out.",
        topology="PC6, PC7 in VLAN 40 (192.168.40.0/24); DHCP server is R1 using ip helper-address.",
        show_output="SW2# show run interface vlan 40\ninterface Vlan40\n ip address 192.168.40.1 255.255.255.0\n (no ip helper-address configured)",
        expected_fault="Missing 'ip helper-address' on the VLAN 40 SVI, so DHCP discover broadcasts never reach the DHCP server.",
        osi_layer="Layer 3", concept="DHCP relay misconfiguration", severity="High",
    ),
    dict(
        id="C007", category="DHCP",
        symptom="PC receives an IP from the wrong subnet (169.254.x.x, APIPA) after a long delay.",
        topology="PC8 in VLAN 10, DHCP pool 'VLAN10_POOL' configured on R1.",
        show_output="R1# show ip dhcp pool\nPool VLAN10_POOL:\n Network: 192.168.10.0 /24\n Leased addresses: 254\n Excluded addresses: 192.168.10.1 - 192.168.10.254",
        expected_fault="Almost the entire pool range is excluded via 'ip dhcp excluded-address', leaving no usable leases (pool exhaustion by misconfiguration).",
        osi_layer="Layer 3", concept="DHCP pool exhaustion / excluded-address error", severity="Medium",
    ),
    dict(
        id="C008", category="DHCP",
        symptom="Two PCs on the same VLAN intermittently lose connectivity and show 'IP address conflict' warnings.",
        topology="PC9 static 192.168.10.50, PC10 DHCP-assigned in the same VLAN 10 pool.",
        show_output="R1# show ip dhcp conflict\nIP address       Detection method   Detection time\n192.168.10.50    Ping               *05:14:22.101",
        expected_fault="Statically assigned address (192.168.10.50) falls inside the active DHCP pool range and was also leased out, causing a duplicate IP.",
        osi_layer="Layer 3", concept="Duplicate IP address", severity="Medium",
    ),
    dict(
        id="C009", category="DNS",
        symptom="PC can ping the file server by IP address but 'ping server.netsage.local' fails to resolve.",
        topology="PC11 (VLAN 10) needs to reach FileServer1 (192.168.50.10) by hostname.",
        show_output="PC11> ipconfig /all\nDNS Servers: 192.168.99.99\nPC11> ping 192.168.50.10  -> Reply from 192.168.50.10\nPC11> ping server.netsage.local -> Ping request could not find host",
        expected_fault="PC's DNS server address (192.168.99.99) does not match the actual DNS server (192.168.50.5); wrong DNS server configured via DHCP option.",
        osi_layer="Layer 7", concept="DNS server misconfiguration", severity="Low",
    ),
    dict(
        id="C010", category="DNS",
        symptom="All PCs in the branch office cannot resolve any internal hostnames, but internet IP connectivity works.",
        topology="Branch DNS server is a Windows Server VM at 192.168.60.5, forwarded via HQ router.",
        show_output="DNS-Server# show ip interface brief\nGigabitEthernet0/0  192.168.60.5  YES manual up   down",
        expected_fault="DNS server's interface line protocol is down (up/down mismatch — Layer 2 issue, likely bad cable/duplex) so the service is unreachable despite the IP being configured.",
        osi_layer="Layer 1/2", concept="Interface line-protocol down", severity="High",
    ),
    dict(
        id="C011", category="Routing",
        symptom="PC in VLAN 10 (192.168.10.0/24) can reach PC in VLAN 20, but not a server in VLAN 30.",
        topology="R1 has sub-interfaces for VLAN 10, 20, 30 (router-on-a-stick). Static routes used between R1 and R2 for VLAN 30's subnet, hosted behind R2.",
        show_output="R1# show ip route\n192.168.10.0/24 is directly connected\n192.168.20.0/24 is directly connected\n(no route for 192.168.30.0/24)",
        expected_fault="Missing static route (or routing protocol advertisement) for 192.168.30.0/24 toward R2.",
        osi_layer="Layer 3", concept="Missing route", severity="High",
    ),
    dict(
        id="C012", category="Routing",
        symptom="Branch site loses connectivity to HQ intermittently; routes flap in the routing table.",
        topology="R1 (Branch) <-> R2 (HQ) running OSPF area 0 over a serial link.",
        show_output="R1# show ip ospf neighbor\nNeighbor ID   Pri  State          Dead Time  Address\n10.0.0.2      1    EXSTART/DR    00:00:31   10.0.0.2",
        expected_fault="OSPF neighbor stuck in EXSTART — usually an MTU mismatch between R1 and R2's serial interfaces preventing DBD exchange.",
        osi_layer="Layer 3", concept="OSPF adjacency / MTU mismatch", severity="High",
    ),
    dict(
        id="C013", category="Routing",
        symptom="Static default route was configured but PCs still cannot reach the internet simulation (ISP router).",
        topology="R1 has 'ip route 0.0.0.0 0.0.0.0 203.0.113.1' pointing to ISP router's WAN interface.",
        show_output="R1# show ip route\nS*  0.0.0.0/0 [1/0] via 203.0.113.1\nR1# ping 203.0.113.1\nRequest timed out.",
        expected_fault="Next-hop 203.0.113.1 is not directly reachable — WAN interface IP/subnet mismatch with the ISP router's interface.",
        osi_layer="Layer 3", concept="Unreachable next-hop / IP addressing error", severity="High",
    ),
    dict(
        id="C014", category="Routing",
        symptom="OSPF routes for VLAN 40 are missing from R2's routing table even though R1 advertises them.",
        topology="R1 and R2 run OSPF area 0; VLAN 40 is directly connected to R1.",
        show_output="R1# show run | section router ospf\nrouter ospf 1\n network 192.168.10.0 0.0.0.255 area 0\n network 192.168.20.0 0.0.0.255 area 0\n(missing: network 192.168.40.0 0.0.0.255 area 0)",
        expected_fault="VLAN 40's subnet is not included in any OSPF network statement, so it is never advertised.",
        osi_layer="Layer 3", concept="Missing OSPF network statement", severity="Medium",
    ),
    dict(
        id="C015", category="ACL",
        symptom="PC in VLAN 10 gets an IP and can ping the gateway, but cannot reach the server in VLAN 30 (Layer 3 works for other VLANs).",
        topology="R1 router-on-a-stick with an inbound ACL applied on the VLAN 10 sub-interface.",
        show_output="R1# show access-lists\nExtended IP access list BLOCK_SALES\n 10 deny ip 192.168.10.0 0.0.0.255 192.168.30.0 0.0.0.255\n 20 permit ip any any",
        expected_fault="ACL 'BLOCK_SALES' explicitly denies VLAN 10 to VLAN 30 traffic, applied inbound on Gi0/0/0.10.",
        osi_layer="Layer 3/4", concept="ACL blocking legitimate traffic", severity="Medium",
    ),
    dict(
        id="C016", category="ACL",
        symptom="Telnet/SSH management access to R2 from the admin subnet suddenly stops working; ping still succeeds.",
        topology="Admin PC 192.168.99.5 manages R2 via SSH (vty lines).",
        show_output="R2# show run | section line vty\nline vty 0 4\n access-class MGMT_ACL in\nR2# show access-lists MGMT_ACL\n10 permit tcp host 192.168.99.50 any eq 22",
        expected_fault="access-class ACL only permits host 192.168.99.50, but the admin PC's real address is 192.168.99.5 — typo/wrong host in ACL.",
        osi_layer="Layer 4", concept="ACL host mismatch on management access", severity="Medium",
    ),
    dict(
        id="C017", category="ACL",
        symptom="Guest Wi-Fi users can reach the internal file server, violating the intended isolation policy.",
        topology="Guest VLAN 50 should only reach the internet simulation, not internal VLANs (10/20/30).",
        show_output="R1# show access-lists\nExtended IP access list GUEST_ISOLATION\n 10 permit ip any any\n(deny statements for internal subnets are missing/placed after the permit)",
        expected_fault="ACL order error: the 'permit ip any any' statement is listed before the deny rules for internal subnets, so it matches first and the isolation never applies.",
        osi_layer="Layer 3", concept="ACL statement ordering error (security)", severity="High",
    ),
    dict(
        id="C018", category="NAT",
        symptom="Internal PCs can ping each other and the router, but cannot reach the simulated ISP/internet cloud.",
        topology="R1 performs PAT (NAT overload) from inside VLANs to outside interface Gi0/2.",
        show_output="R1# show ip nat translations\n(empty)\nR1# show run | include ip nat\nip nat inside source list 1 interface GigabitEthernet0/2 overload\ninterface GigabitEthernet0/1\n(no 'ip nat inside' applied)",
        expected_fault="'ip nat inside' is missing on the internal-facing interface, so NAT never triggers even though the outside/overload config is correct.",
        osi_layer="Layer 3", concept="NAT inside/outside interface not marked", severity="High",
    ),
    dict(
        id="C019", category="NAT",
        symptom="Some internal hosts can reach the internet simulation, others in the same VLAN cannot.",
        topology="NAT ACL (access-list 1) defines which source subnets are translated.",
        show_output="R1# show access-lists 1\nStandard IP access list 1\n 10 permit 192.168.10.0 0.0.0.15",
        expected_fault="NAT ACL wildcard mask (0.0.0.15) only covers 192.168.10.0-15, excluding the rest of the /24 subnet's hosts from translation.",
        osi_layer="Layer 3", concept="Incorrect ACL wildcard mask for NAT", severity="Medium",
    ),
    dict(
        id="C020", category="NAT",
        symptom="Port-forwarded web server (static NAT) is unreachable from the simulated internet.",
        topology="Static NAT: inside local 192.168.10.100 -> inside global 203.0.113.50, TCP 80.",
        show_output="R1# show run | include ip nat inside source static\nip nat inside source static tcp 192.168.10.100 8080 203.0.113.50 80\nWebServer real port: 80",
        expected_fault="Static NAT maps inside local port 8080 instead of 80 — port number mismatch between NAT rule and the server's actual listening port.",
        osi_layer="Layer 4", concept="Static NAT port mismatch", severity="Medium",
    ),
    dict(
        id="C021", category="Wireless",
        symptom="Laptop shows 'Wi-Fi connected' with a valid IP but cannot ping the gateway or any wired host.",
        topology="Laptop associates to WLAN 'CORP-WIFI' on AP1, mapped to VLAN 10, AP1 uplink to SW1 Fa0/12.",
        show_output="SW1# show interfaces fa0/12 switchport\nAdministrative Mode: access\nAccess Mode VLAN: 99 (unused)",
        expected_fault="AP uplink switchport is in VLAN 99 instead of VLAN 10, so wireless traffic lands in a VLAN with no gateway/DHCP for it.",
        osi_layer="Layer 2", concept="AP uplink port VLAN mismatch", severity="Medium",
    ),
    dict(
        id="C022", category="Wireless",
        symptom="Devices repeatedly fail to associate to the corporate WLAN, showing 'authentication failed'.",
        topology="WLAN 'CORP-WIFI' configured with WPA2-PSK on the wireless router/AP.",
        show_output="AP1# show running-config (GUI equiv.)\nSSID: CORP-WIFI\nSecurity: WPA2-PSK\nPassphrase: (blank/mismatched vs. client config)",
        expected_fault="Passphrase configured on the AP does not match what end users were issued — pre-shared key mismatch.",
        osi_layer="Layer 2", concept="WLAN authentication (PSK mismatch)", severity="Low",
    ),
    dict(
        id="C023", category="Wireless",
        symptom="Wireless clients connect fine near the AP but drop connection and roam poorly at the far end of the building.",
        topology="Two APs (AP1, AP2) cover the same floor on overlapping channels.",
        show_output="AP1: Channel 6, Power: 100%\nAP2: Channel 6, Power: 100%",
        expected_fault="Co-channel interference — both APs on the same channel at full power causes contention/roaming issues rather than a config fault.",
        osi_layer="Layer 1", concept="RF channel overlap / interference", severity="Low",
    ),
    dict(
        id="C024", category="VLAN",
        symptom="After adding a new switch (SW3) to the network, PCs behind it can't reach any other VLAN, only local VLAN 10.",
        topology="SW3 connects to SW1 via Gi0/1, intended as a trunk carrying VLANs 10, 20, 30.",
        show_output="SW3# show interfaces gi0/1 switchport\nAdministrative Mode: static access\nOperational Mode: static access",
        expected_fault="Uplink port on SW3 was left as an access port instead of being configured as a trunk (switchport mode trunk).",
        osi_layer="Layer 2", concept="Trunk not configured on new switch uplink", severity="High",
    ),
    dict(
        id="C025", category="Gateway",
        symptom="PC's ping to default gateway works, but ping to any other subnet's gateway or host fails with 'Destination host unreachable'.",
        topology="PC26 in VLAN 20, default gateway is HSRP virtual IP shared by R1/R2.",
        show_output="R1# show standby brief\nInterface  Grp  Pri  P State   Active     Standby    Virtual IP\nGi0/0.20   20   100  P Active  local      unknown    192.168.20.1\nR2# show standby brief\nInterface  Grp  Pri  P State   Active     Standby    Virtual IP\nGi0/0.20   20   90   P Init    unknown    unknown    192.168.20.2",
        expected_fault="HSRP standby router (R2) is stuck in Init state (likely mismatched HSRP group/authentication), so failover/backup path for VLAN 20 is not functioning, and the only forwarding path has an upstream routing gap.",
        osi_layer="Layer 3", concept="HSRP first-hop redundancy misconfiguration", severity="Medium",
    ),
    dict(
        id="C026", category="DHCP",
        symptom="PC obtains an IP in the 192.168.10.0/24 range but with subnet mask 255.255.255.128, causing it to treat the gateway as unreachable.",
        topology="DHCP pool VLAN10_POOL should hand out 255.255.255.0 masks.",
        show_output="R1# show run | section dhcp pool VLAN10_POOL\nip dhcp pool VLAN10_POOL\n network 192.168.10.0 255.255.255.128\n default-router 192.168.10.1",
        expected_fault="DHCP pool network statement uses the wrong mask (/25 instead of /24), splitting the pool and gateway into different logical subnets from the client's perspective.",
        osi_layer="Layer 3", concept="Wrong subnet mask in DHCP pool", severity="High",
    ),
    dict(
        id="C027", category="Routing",
        symptom="Two branch routers using EIGRP fail to form a neighbor relationship.",
        topology="R3 (Branch A, AS 100) and R4 (Branch B, AS 200) connected via a shared serial link.",
        show_output="R3# show ip eigrp neighbors\n(empty)\nR3# show run | section router eigrp\nrouter eigrp 100\nR4# show run | section router eigrp\nrouter eigrp 200",
        expected_fault="Mismatched EIGRP autonomous system numbers (100 vs 200) between the two routers prevent neighbor formation.",
        osi_layer="Layer 3", concept="EIGRP AS number mismatch", severity="High",
    ),
    dict(
        id="C028", category="ACL",
        symptom="FTP file transfers to the server fail (control connection connects, but data never transfers) while other TCP apps work fine.",
        topology="ACL on R1 restricts VLAN 10 to only common ports toward the server subnet.",
        show_output="R1# show access-lists FTP_RESTRICT\n10 permit tcp any host 192.168.50.10 eq 21\n20 deny ip any any",
        expected_fault="ACL only permits TCP port 21 (control) but blocks the FTP data channel (port 20 / passive high ports), breaking active/passive FTP transfers.",
        osi_layer="Layer 4/7", concept="ACL missing required application ports", severity="Medium",
    ),
    dict(
        id="C029", category="VLAN",
        symptom="Voice VLAN phones fail to get IP addresses while PCs plugged into the same switch ports work fine.",
        topology="SW1 Fa0/5 has both an IP phone and a PC daisy-chained, using a separate voice VLAN 100.",
        show_output="SW1# show run interface fa0/5\ninterface FastEthernet0/5\n switchport mode access\n switchport access vlan 10\n (no 'switchport voice vlan 100' command)",
        expected_fault="Voice VLAN is not configured on the port, so the phone's tagged voice VLAN traffic is dropped/untagged into the data VLAN.",
        osi_layer="Layer 2", concept="Missing voice VLAN configuration", severity="Medium",
    ),
    dict(
        id="C030", category="NAT",
        symptom="After a router reboot, all internal hosts lose internet simulation access even though the config looks unchanged in 'show running-config'.",
        topology="NAT overload config relies on access-list 1 defined via numbered ACL.",
        show_output="R1# show startup-config | include access-list\n(no output)\nR1# show running-config | include access-list\naccess-list 1 permit 192.168.10.0 0.0.0.255",
        expected_fault="Configuration was never saved (write memory / copy run start), so the numbered ACL used by NAT was lost on reload.",
        osi_layer="Layer 3", concept="Unsaved configuration lost on reload", severity="High",
    ),
    dict(
        id="C031", category="Routing",
        symptom="Summarized route to branch subnets causes one specific /24 to become unreachable while others in the summary work.",
        topology="R2 advertises a summary route 192.168.8.0/21 covering VLANs 10-13's subnets (192.168.8.0-192.168.15.255) toward HQ.",
        show_output="HQ-R1# show ip route\nO IA  192.168.8.0/21 [110/20] via 10.0.0.2\nHQ-R1# ping 192.168.12.1\nRequest timed out.",
        expected_fault="192.168.12.0/24 is inside the summarized range (192.168.8.0/21 = .8.0-.15.255) but is not actually configured/connected behind R2 (black-holed by the summary — route exists but no real path to that specific subnet).",
        osi_layer="Layer 3", concept="Route summarization black-hole", severity="Medium",
    ),
    dict(
        id="C032", category="DNS",
        symptom="Internal hostname resolution works for servers but fails specifically for the newly added 'hr.netsage.local' record.",
        topology="DNS server hosts an internal zone 'netsage.local'.",
        show_output="DNS-Server> show zone netsage.local\nfileserver.netsage.local  A  192.168.50.10\nmailserver.netsage.local  A  192.168.50.11\n(no record for hr.netsage.local)",
        expected_fault="A record for hr.netsage.local was never created in the DNS zone after the server was deployed.",
        osi_layer="Layer 7", concept="Missing DNS resource record", severity="Low",
    ),
]

FIELDS = ["case_id", "category", "symptom", "topology_note", "show_output",
          "expected_fault", "osi_layer", "concept_tag", "severity"]

def main():
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "cases.csv")
    out_path = os.path.abspath(out_path)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDS)
        for c in CASES:
            writer.writerow([
                c["id"], c["category"], c["symptom"], c["topology"],
                c["show_output"], c["expected_fault"], c["osi_layer"],
                c["concept"], c["severity"],
            ])
    print(f"Wrote {len(CASES)} cases to {out_path}")

if __name__ == "__main__":
    main()
