# crisp.py
# Copyright (c) 2025 Kurt Kristoff Nitsch 
# Licensed under the MIT License. See LICENSE file in the repository root.

import unittest
import struct
import time
import hashlib
import crc32c
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

class CrispConfig:
    def __init__(self):
        self.use_vector_clocks = True
        self.use_quorums = True
        self.use_hierarchical_gossip = True
        self.compression = "huffman"

class PriorityQueue:
    def __init__(self, priority):
        self.priority = priority
    def send(self, node, packet):
        pass

class BTree:
    def __init__(self):
        self.nodes = {}
    def insert(self, key, value):
        self.nodes[key] = value
        return key
    def search(self, key):
        return type('Node', (), {'key': key}) if key in self.nodes else None

class LRUCache:
    def __init__(self, max_size):
        self.cache = {}
        self.order = []
        self.max_size = max_size

    def put(self, key, value):
        if key in self.cache:
            self.order.remove(key)
        elif len(self.cache) >= self.max_size:
            del self.cache[self.order.pop(0)]
        self.cache[key] = value
        self.order.append(key)

    def get(self, key):
        if key in self.cache:
            self.order.remove(key)
            self.order.append(key)
            return self.cache[key]
        return None

class CrispPacket:
    HEADER_FORMAT = "!BHI4s"
    HEADER_SIZE = 12
    ERROR_CODES = {
        0x0001: "Malformed packet",
        0x0003: "SKC ID not found",
        0x0007: "Version conflict",
        0x0008: "Sync failed after retries",
        0x0009: "Invalid Merkle root",
        0x000A: "Unauthorized update",
        0x000B: "Deadlock timeout",
    }

    def __init__(self, type_id, payload, sequence=None, checksum_type=0x01):
        self.type_id = type_id
        self.sequence = sequence or int(time.time() * 1000)
        self.payload = payload
        self.checksum_type = checksum_type
        self.checksum = self._calculate_checksum()
        self.timestamp = time.time()
        self.retry_count = 0

    def _calculate_checksum(self):
        return struct.pack("!I", crc32c.crc32(self.payload)) if self.checksum_type == 0x01 else hashlib.sha256(self.payload).digest()[:4]

    def encode(self):
        header = struct.pack(self.HEADER_FORMAT, self.type_id, len(self.payload) + self.HEADER_SIZE,
                            self.sequence, self.checksum)
        return header + self.payload

    @staticmethod
    def decode(data):
        if len(data) < CrispPacket.HEADER_SIZE:
            raise ValueError("Packet too short")
        type_id, length, sequence, checksum = struct.unpack(CrispPacket.HEADER_FORMAT, data[:CrispPacket.HEADER_SIZE])
        payload = data[CrispPacket.HEADER_SIZE:length]
        packet = CrispPacket(type_id, payload, sequence, checksum_type=0x01)
        if packet.checksum != packet._calculate_checksum():
            raise ValueError("Checksum mismatch")
        return packet

    def needs_ack(self):
        return self.type_id in [0x60, 0x61, 0x63, 0x67, 0x68, 0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F, 0x70]

    def is_expired(self):
        return time.time() - self.timestamp > 5

    @staticmethod
    def create_error_response(correlation_id, original_type, error_code, error_message):
        msg_bytes = error_message.encode()
        payload = struct.pack("!QBHH", correlation_id, original_type, error_code, len(msg_bytes)) + msg_bytes
        return CrispPacket(0xE0, payload)

class MerkleTree:
    def __init__(self):
        self.leaves = []

    def add_leaf(self, entry):
        self.leaves.append(hashlib.sha256(entry).digest())

    def get_root(self):
        if not self.leaves:
            return b"\x00" * 32
        leaves = self.leaves[:]
        while len(leaves) > 1:
            new_leaves = []
            for i in range(0, len(leaves), 2):
                pair = leaves[i:i+2]
                new_leaves.append(hashlib.sha256(b"".join(pair)).digest())
            leaves = new_leaves
        return leaves[0]

class SKCManager:
    def __init__(self, node_id, config=CrispConfig(), private_key=None):
        self.node_id = node_id
        self.config = config
        self.private_key = private_key or ec.generate_private_key(ec.SECP256R1())
        self.public_key = self.private_key.public_key()
        self.skc_version = 1
        self.vector_clock = {node_id: 0} if config.use_vector_clocks else None
        self.reputation = {node_id: 1.0}
        self.quorum_threshold = 3 if config.use_quorums else 1
        self.merkle_tree = MerkleTree()
        self.storage = {}
        self.cache = {}
        self.lru_cache = LRUCache(max_size=1000)
        self.access_counts = {}
        self.b_tree = BTree()
        self.partition_map = {}
        self.neighbors = ["node2", "node3"]
        self.cluster_leaders = ["leader1"] if config.use_hierarchical_gossip else None
        self.sync_interval = 1.0

    def huffman_encode(self, data):
        return data[:16]  # Simulated Huffman encoding

    def sign_packet(self, packet):
        payload = packet.payload
        signature = self.private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
        payload += struct.pack("!H", 1) + signature[:32]
        return CrispPacket(packet.type_id, payload)

    def verify_signature(self, packet, public_keys):
        sig_count = struct.unpack("!H", packet.payload[-2:])[0]
        sig_len = 32
        signatures = [packet.payload[-2-i*sig_len-sig_len:-2-i*sig_len] for i in range(sig_count)]
        payload = packet.payload[:-2-sig_count*sig_len]
        verified = 0
        for sig, pub in zip(signatures, public_keys):
            try:
                pub.verify(sig, payload, ec.ECDSA(hashes.SHA256()))
                verified += 1
            except:
                continue
        return verified >= self.quorum_threshold

    def encode_vector_clock(self):
        if not self.config.use_vector_clocks:
            return b""
        self.trim_vector_clock(10)
        return struct.pack("!I", len(self.vector_clock)) + b"".join(struct.pack("!32sI", k.encode(), v) for k, v in self.vector_clock.items())

    def trim_vector_clock(self, max_nodes):
        if self.config.use_vector_clocks and len(self.vector_clock) > max_nodes:
            self.vector_clock = dict(sorted(self.vector_clock.items(), key=lambda x: x[1], reverse=True)[:max_nodes])

    def sync_skc(self, id_range_start, id_range_end, entries, priority=None):
        if self.config.use_vector_clocks:
            self.vector_clock[self.node_id] = self.vector_clock.get(self.node_id, 0) + 1
        self.merkle_tree.add_leaf(entries)
        self.b_tree.insert(id_range_start, entries)
        key = f"{id_range_start}:{id_range_end}"
        self.access_counts[key] = self.access_counts.get(key, 0) + 1
        priority = 0x02 if self.access_counts[key] > 10 else (priority or 0x00)
        if priority == 0x02:
            self.lru_cache.put(key, entries)
        clock_bytes = self.encode_vector_clock()
        payload = struct.pack("!IBHQQ16sH", self.skc_version, priority, 1, id_range_start, id_range_end,
                             self.huffman_encode(self.merkle_tree.get_root()), len(clock_bytes)) + clock_bytes
        packet = CrispPacket(0x60, payload)
        signed_packet = self.sign_packet(packet)
        return self.gossip_sync(signed_packet)

    def synthesize_knowledge(self, source_ids, synthesized_entry, entry_type="causal"):
        payload = struct.pack("!IHQ", self.skc_version, len(source_ids), len(synthesized_entry)) + \
                  b"".join(struct.pack("!Q", sid) for sid in source_ids) + synthesized_entry.encode()
        packet = CrispPacket(0x69, payload)
        return self.sign_packet(packet)

    def validate_semantics(self, entry_id, schema_id, validation_result):
        payload = struct.pack("!QQB", entry_id, schema_id, validation_result)
        packet = CrispPacket(0x6A, payload)
        return self.sign_packet(packet)

    def update_global_partition_directory(self, partition_mappings):
        payload = struct.pack("!IH", self.skc_version, len(partition_mappings))
        for part_id, node_id in partition_mappings:
            payload += struct.pack("!Q32s", part_id, node_id.encode())
        packet = CrispPacket(0x6B, payload)
        return self.sign_packet(packet)

    def share_reasoning_trace(self, entry_id, trace_data):
        payload = struct.pack("!QH", entry_id, len(trace_data)) + trace_data.encode()
        packet = CrispPacket(0x6C, payload)
        return self.sign_packet(packet)

    def priority_broadcast(self, id_range_start, id_range_end, micro_entry):
        payload = struct.pack("!IQQ8s", self.skc_version, id_range_start, id_range_end, self.huffman_encode(micro_entry)[:8])
        packet = CrispPacket(0x6D, payload)
        return self.sign_packet(packet)

    def ethics_check(self, entry_id, alignment_score, safety_flag):
        payload = struct.pack("!QfB", entry_id, alignment_score, safety_flag)
        packet = CrispPacket(0x6E, payload)
        return self.sign_packet(packet)

    def send_adapter_packet(self, target_protocol, payload):
        payload = struct.pack("!H", len(target_protocol)) + target_protocol.encode() + payload
        packet = CrispPacket(0x6F, payload)
        return self.sign_packet(packet)

    def lightweight_sync(self, id_range_start, id_range_end, entries):
        payload = struct.pack("!IQQ8s", self.skc_version, id_range_start, id_range_end, self.huffman_encode(entries)[:8])
        packet = CrispPacket(0x70, payload)
        return self.sign_packet(packet)

    def add_provenance(self, entry_id, causal_chain):
        payload = struct.pack("!QH", entry_id, len(causal_chain)) + causal_chain.encode()
        packet = CrispPacket(0x50, payload)
        return self.sign_packet(packet)

    def gossip_sync(self, packet, cluster_leaders=None):
        priority = 0x03 if packet.type_id == 0x6D else struct.unpack("!IB", packet.payload[:5])[1]
        queue = PriorityQueue(priority)
        targets = cluster_leaders if self.config.use_hierarchical_gossip and cluster_leaders else self.neighbors
        for node in targets:
            self.storage[f"skc_sync:{node}:{self.skc_version}"] = packet.encode()
        return self.check_conflict(packet) or packet

    def adjust_sync_interval(self):
        beacon_count = sum(1 for n in self.neighbors if self.storage.get(f"beacon:{n}"))
        self.sync_interval = 1.0 if beacon_count > len(self.neighbors) * 0.7 else 5.0

    def check_conflict(self, incoming_packet):
        if not self.config.use_vector_clocks:
            return None
        try:
            version, priority, count, start, end, hash_val = struct.unpack("!IBHQQ16s", incoming_packet.payload[:39])
        except struct.error:
            return CrispPacket.create_error_response(incoming_packet.sequence, incoming_packet.type_id, 0x0001, "Invalid packet format")
        stored = self.storage.get(f"skc_sync:{self.node_id}:{version}")
        if stored:
            stored_packet = CrispPacket.decode(stored)
            if stored_packet:
                try:
                    stored_hash = stored_packet.payload[23:39]
                    if stored_hash != hash_val:
                        return self.resolve_semantic_conflict(incoming_packet, stored_packet)
                except IndexError:
                    return CrispPacket.create_error_response(incoming_packet.sequence, incoming_packet.type_id, 0x0001, "Invalid stored packet")
        return self.resolve_deadlock(incoming_packet)

    def resolve_semantic_conflict(self, incoming, stored):
        votes = self.collect_votes([incoming, stored])
        return votes[0] if votes else CrispPacket.create_error_response(incoming.sequence, incoming_packet.type_id, 0x0007, "Conflict unresolved")

    def collect_votes(self, packets):
        votes = {p.sequence: 0 for p in packets}
        for node in self.neighbors:
            vote = self.storage.get(f"vote:{node}")
            if vote in votes:
                votes[vote] += self.reputation.get(node, 0)
        return sorted(packets, key=lambda p: votes[p.sequence], reverse=True)

    def resolve_deadlock(self, packet):
        if packet.is_expired():
            self.storage[f"deadlock:{packet.sequence}"] = packet.encode()
            return CrispPacket.create_error_response(packet.sequence, packet.type_id, 0x000B, "Deadlock timeout")
        return None

class TestCrispAGIEnhancements(unittest.TestCase):
    def setUp(self):
        self.node_id = "node1"
        self.config = CrispConfig()
        self.manager = SKCManager(self.node_id, self.config)
        self.public_keys = [
            self.manager.public_key,
            SKCManager("cosigner1").public_key,
            SKCManager("cosigner2").public_key,
            SKCManager("cosigner3").public_key
        ]

    def test_knowledge_synthesis(self):
        packet = self.manager.synthesize_knowledge([1, 2], '{"type":"causal"}')
        decoded = CrispPacket.decode(packet.encode())
        version, count = struct.unpack("!IH", decoded.payload[:6])
        self.assertEqual(count, 2)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_semantic_validation(self):
        packet = self.manager.validate_semantics(1000, 12345, 1)
        decoded = CrispPacket.decode(packet.encode())
        entry_id, schema_id, result = struct.unpack("!QQB", decoded.payload)
        self.assertEqual(entry_id, 1000)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_global_partitioning(self):
        packet = self.manager.update_global_partition_directory([(1, "node2")])
        decoded = CrispPacket.decode(packet.encode())
        version, count = struct.unpack("!IH", decoded.payload[:6])
        self.assertEqual(count, 1)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_reasoning_trace(self):
        packet = self.manager.share_reasoning_trace(1000, '{"step":"infer"}')
        decoded = CrispPacket.decode(packet.encode())
        entry_id, length = struct.unpack("!QH", decoded.payload[:10])
        self.assertEqual(entry_id, 1000)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_priority_broadcast(self):
        packet = self.manager.priority_broadcast(1000, 2000, b"micro")
        decoded = CrispPacket.decode(packet.encode())
        version, start, end = struct.unpack("!IQQ", decoded.payload[:20])
        self.assertEqual(start, 1000)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_ethics_check(self):
        packet = self.manager.ethics_check(1000, 0.9, 1)
        decoded = CrispPacket.decode(packet.encode())
        entry_id, score, flag = struct.unpack("!QfB", decoded.payload)
        self.assertEqual(score, 0.9)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_adapter_packet(self):
        packet = self.manager.send_adapter_packet("ROS", b"data")
        decoded = CrispPacket.decode(packet.encode())
        proto_len = struct.unpack("!H", decoded.payload[:2])[0]
        self.assertEqual(proto_len, 3)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_lightweight_sync(self):
        packet = self.manager.lightweight_sync(1000, 2000, b"edge")
        decoded = CrispPacket.decode(packet.encode())
        self.assertLess(len(decoded.payload), 40)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_provenance_causal_chain(self):
        packet = self.manager.add_provenance(1000, '{"cause":"source1"}')
        decoded = CrispPacket.decode(packet.encode())
        entry_id, length = struct.unpack("!QH", decoded.payload[:10])
        self.assertEqual(entry_id, 1000)
        self.assertTrue(self.manager.verify_signature(packet, self.public_keys))

    def test_adaptive_resilience(self):
        self.manager.storage["beacon:node2"] = True
        interval = self.manager.adjust_sync_interval()
        self.assertEqual(interval, 1.0)

if __name__ == "__main__":
    unittest.main()
