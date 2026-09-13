#!/usr/bin/env python3
"""
NetSage AI — Deterministic Rule Checker

Runs simple, explainable, non-AI checks over parsed device config/state
snippets to catch common Cisco lab config mistakes:
  - duplicate IP addresses
  - wrong subnet mask
  - gateway mismatch (gateway not in host's subnet)
  - interface administratively down / line protocol down
  - missing VLAN assignment (access port left on VLAN 1)
  - missing route for a subnet a host needs to reach

This is meant to run BEFORE or AFTER the AI diagnosis as a sanity net:
things this script catches deterministically should never be missed by
the AI, and should be used to validate/ground the AI's evidence field.

Usage:
    python3 scripts/rule_checker.py --devices data/device_snapshots.json
    python3 scripts/rule_checker.py --devices data/device_snapshots.json --json out.json
"""
import argparse
import ipaddress
import json
import sys
from collections import defaultdict


def check_duplicate_ips(hosts):
    """hosts: list of {name, ip, mask, source} -> flags any ip used twice."""
    findings = []
    seen = defaultdict(list)
    for h in hosts:
        seen[h["ip"]].append(h["name"])
    for ip, names in seen.items():
        if len(names) > 1:
            findings.append({
                "check": "duplicate_ip",
                "severity": "High",
                "detail": f"IP {ip} is used by more than one host: {', '.join(names)}",
            })
    return findings


def check_wrong_mask(hosts, expected_masks):
    """expected_masks: dict of subnet-cidr(no host bits) -> expected prefixlen."""
    findings = []
    for h in hosts:
        try:
            iface = ipaddress.ip_interface(f"{h['ip']}/{h['mask']}")
        except ValueError:
            findings.append({
                "check": "wrong_mask",
                "severity": "Medium",
                "detail": f"{h['name']}: could not parse ip/mask {h['ip']}/{h['mask']}",
            })
            continue
        net = str(iface.network.network_address)
        expected = expected_masks.get(net)
        if expected is not None and iface.network.prefixlen != expected:
            findings.append({
                "check": "wrong_mask",
                "severity": "High",
                "detail": (f"{h['name']} ({h['ip']}) has prefix /{iface.network.prefixlen} "
                           f"but the documented subnet {net} should be /{expected}."),
            })
    return findings


def check_gateway_mismatch(hosts):
    findings = []
    for h in hosts:
        gw = h.get("gateway")
        if not gw:
            continue
        try:
            host_net = ipaddress.ip_interface(f"{h['ip']}/{h['mask']}").network
            gw_ip = ipaddress.ip_address(gw)
        except ValueError:
            continue
        if gw_ip not in host_net:
            findings.append({
                "check": "gateway_mismatch",
                "severity": "High",
                "detail": (f"{h['name']}: gateway {gw} is not inside its own subnet "
                           f"{host_net} (ip {h['ip']}/{h['mask']})."),
            })
    return findings


def check_interfaces_down(interfaces):
    """interfaces: list of {device, name, admin_status, line_status}."""
    findings = []
    for i in interfaces:
        if i.get("admin_status", "").lower() == "administratively down":
            findings.append({
                "check": "interface_admin_down",
                "severity": "High",
                "detail": f"{i['device']} {i['name']} is administratively down (shutdown).",
            })
        elif i.get("line_status", "").lower() == "down" and i.get("admin_status", "").lower() == "up":
            findings.append({
                "check": "interface_line_down",
                "severity": "High",
                "detail": (f"{i['device']} {i['name']} is up/administratively but line protocol "
                           f"is down — check cabling, duplex, or far-end config."),
            })
    return findings


def check_missing_vlan(ports, expected_vlan_by_port):
    """ports: list of {device, name, mode, access_vlan}."""
    findings = []
    for p in ports:
        key = (p["device"], p["name"])
        expected = expected_vlan_by_port.get(key)
        if expected is None:
            continue
        if p.get("mode") == "access" and p.get("access_vlan") != expected:
            findings.append({
                "check": "missing_or_wrong_vlan",
                "severity": "Medium",
                "detail": (f"{p['device']} {p['name']} is access VLAN "
                           f"{p.get('access_vlan')} but should be VLAN {expected}."),
            })
    return findings


def check_missing_routes(routing_tables, required_reachability):
    """
    routing_tables: {device: [subnet_cidr, ...]} (subnets/routes known on that device)
    required_reachability: list of {device, needs_subnet} pairs that must be routed
    """
    findings = []
    for req in required_reachability:
        dev = req["device"]
        needed = ipaddress.ip_network(req["needs_subnet"])
        known = [ipaddress.ip_network(s) for s in routing_tables.get(dev, [])]
        if not any(needed.subnet_of(k) or needed == k for k in known):
            findings.append({
                "check": "missing_route",
                "severity": "High",
                "detail": f"{dev} has no route covering {needed} — required for reachability.",
            })
    return findings


def run_all(data):
    findings = []
    findings += check_duplicate_ips(data.get("hosts", []))
    findings += check_wrong_mask(data.get("hosts", []), data.get("expected_masks", {}))
    findings += check_gateway_mismatch(data.get("hosts", []))
    findings += check_interfaces_down(data.get("interfaces", []))
    findings += check_missing_vlan(
        data.get("ports", []),
        {tuple(k.split("|")): v for k, v in data.get("expected_vlan_by_port", {}).items()},
    )
    findings += check_missing_routes(data.get("routing_tables", {}), data.get("required_reachability", []))
    return findings


def main():
    ap = argparse.ArgumentParser(description="NetSage AI deterministic rule checker")
    ap.add_argument("--devices", required=True, help="Path to device_snapshots.json")
    ap.add_argument("--json", help="Optional path to also write findings as JSON")
    args = ap.parse_args()

    with open(args.devices) as f:
        data = json.load(f)

    findings = run_all(data)

    if not findings:
        print("No deterministic rule violations found.")
    else:
        print(f"{len(findings)} finding(s):\n")
        for f_ in findings:
            print(f"[{f_['severity']:>6}] {f_['check']}: {f_['detail']}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(findings, f, indent=2)
        print(f"\nWrote findings to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
