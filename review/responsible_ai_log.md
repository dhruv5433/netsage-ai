# NetSage AI — Responsible AI Log

This log records every case where **qwen3:8b's** actual diagnosis (run locally via Ollama, see `scripts/run_ai_diagnosis.py`) was corrected (Edited) or overruled (Rejected) by a human reviewer, as required by the project's Safety Rule: a human must approve or correct every diagnosis before it is treated as a fix.

**Summary:** 32 cases reviewed — 25 Accepted, 5 Edited, 2 Rejected. AI/human agreement rate: 78.1%.

---

## 1. Case C004 — Gateway (Edited)

**Symptom:** PC gets a valid IP via DHCP but cannot ping anything outside its own subnet, including the router.

**AI diagnosis (qwen3:8b):** PC4 has an incorrect default gateway configured (192.168.20.1) that does not match its VLAN 10 subnet (192.168.10.0/24).
(confidence: medium)

**Corrected root cause:** DHCP pool's 'default-router' statement for VLAN 10 points to the wrong subnet's gateway (192.168.20.1 instead of 192.168.10.1).

**Why it was corrected:** AI correctly spotted the gateway/subnet mismatch from the PC's ipconfig output, but it wasn't given the DHCP pool config and defaulted to 'fix it on the PC.' Since this PC gets its address via DHCP, the real fix is on the DHCP pool's default-router line, not a manual static change on the client. Corrected the root cause to point at the server-side config; kept AI's evidence read as accurate.

**Reviewer decision:** Edited

---

## 2. Case C009 — DNS (Rejected)

**Symptom:** PC can ping the file server by IP address but 'ping server.netsage.local' fails to resolve.

**AI diagnosis (qwen3:8b):** DNS server (192.168.99.99) does not have an A record for 'server.netsage.local'.
(confidence: medium)

**Corrected root cause:** PC's configured DNS server address (192.168.99.99) does not match the network's real DNS server (192.168.50.5) -- the PC is asking the wrong device, which is why lookups fail while ping-by-IP still works.

**Why it was corrected:** AI incorrectly assumed the DNS server it saw referenced (192.168.99.99) was correct and hypothesized a missing record on it. That address is not the documented DNS server for this network at all -- the AI never questioned whether the PC was even pointed at the right server. Its proposed fix (add a record on 192.168.99.99) would not resolve the problem and risks configuring the wrong box. Rejected rather than edited because the fix direction was wrong, not just incomplete.

**Reviewer decision:** Rejected

---

## 3. Case C012 — Routing (Edited)

**Symptom:** Branch site loses connectivity to HQ intermittently; routes flap in the routing table.

**AI diagnosis (qwen3:8b):** OSPF adjacency is stuck in EXSTART/DR state due to potential timer mismatches or DBD packet exchange issues
(confidence: medium)

**Corrected root cause:** OSPF neighbor stuck in EXSTART/DR is the classic signature of an MTU mismatch between R1 and R2's serial interfaces blocking the DBD exchange, not a timer or authentication issue.

**Why it was corrected:** AI's evidence read (EXSTART/DR, 00:00:31 dead timer) was accurate, but it offered a generic list of possible causes (timers, network type, authentication) instead of naming the specific, well-known cause for this exact symptom pattern. Its 'next_command' (show ip ospf interface) would have surfaced the MTU values and let a human confirm this, so the diagnosis was salvageable but too vague to accept as-is.

**Reviewer decision:** Edited

---

## 4. Case C013 — Routing (Edited)

**Symptom:** Static default route was configured but PCs still cannot reach the internet simulation (ISP router).

**AI diagnosis (qwen3:8b):** Missing route to ISP's WAN network (203.0.113.0/24) preventing default route validation
(confidence: medium)

**Corrected root cause:** The next-hop 203.0.113.1 is not directly reachable because of an IP addressing mismatch on the WAN interface facing the ISP router, not a missing route.

**Why it was corrected:** AI's own evidence (ping to the next-hop times out) is the right observation, but it then diagnosed a 'missing route to the ISP network' -- a static default route to an unreachable next-hop is an addressing/reachability problem on the WAN link, not something a second route would fix. Corrected the root cause to point at the interface addressing rather than routing table entries.

**Reviewer decision:** Edited

---

## 5. Case C017 — ACL (Edited)

**Symptom:** Guest Wi-Fi users can reach the internal file server, violating the intended isolation policy.

**AI diagnosis (qwen3:8b):** The ACL 'GUEST_ISOLATION' permits all traffic (any any) instead of restricting access to internal VLANs 10/20/30.
(confidence: high)

**Corrected root cause:** The ACL's deny rules for internal subnets exist but are ordered AFTER the 'permit ip any any' line, so they never match -- this is a rule-ordering bug, not a missing-rule bug.

**Why it was corrected:** AI's root_cause said the deny statements were 'missing/deferred' and its fix was to add new deny rules before the permit -- functionally this happens to fix the symptom, but it mischaracterizes the bug (the rules already exist) and could leave a confusing, partially-duplicated ACL if applied literally. Corrected the wording so the actual fix is 'reorder existing rules', not 'author new ones'.

**Reviewer decision:** Edited

---

## 6. Case C025 — Gateway (Edited)

**Symptom:** PC's ping to default gateway works, but ping to any other subnet's gateway or host fails with 'Destination host unreachable'.

**AI diagnosis (qwen3:8b):** HSRP virtual IP mismatch between R1 and R2 for VLAN 20
(confidence: high)

**Corrected root cause:** R2's HSRP standby is stuck in Init state (config-level HSRP problem, e.g. group number or authentication mismatch) rather than a virtual-IP mismatch.

**Why it was corrected:** AI read the two 'show standby brief' outputs and noticed R1 and R2 display different virtual IPs -- which is a legitimate observation and actually exposed an inconsistency in how this case's evidence was written up (two HSRP peers in the same group should always show the same virtual IP). Since the case's intended lesson is 'a peer stuck in Init blocks failover,' the corrected answer keeps that framing but this case's evidence data itself needs to be fixed before reuse -- flagging that separately, not blaming the model.

**Reviewer decision:** Edited

---

## 7. Case C031 — Routing (Rejected)

**Symptom:** Summarized route to branch subnets causes one specific /24 to become unreachable while others in the summary work.

**AI diagnosis (qwen3:8b):** The summarized route 192.168.0.0/22 does not include the subnet containing 192.168.12.1.
(confidence: high)

**Corrected root cause:** 192.168.12.0/24 is not covered by the 192.168.0.0/22 summary at all (that summary only spans 192.168.0.0-192.168.3.255) -- the case's own topology note is inconsistent (it claims the /22 summary covers VLANs 10-13, which it mathematically cannot), so this case needs to be rewritten with a summary range that actually contains the affected subnet before it's usable for grading or the demo.

**Why it was corrected:** AI attempted the subnetting math, got the boundary arithmetic wrong (claimed 192.168.12.1 'falls in 192.168.8.0/21'), but in the process correctly noticed the summary doesn't actually contain the address in question. Rejected because both the AI's math and the case's own premise are wrong -- this is flagged as a case-data bug to fix in cases.csv, not just an AI error, and shouldn't be used to score model accuracy until corrected.

**Reviewer decision:** Rejected

---

