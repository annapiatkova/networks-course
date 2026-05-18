import os
import select
import socket
import struct
import sys
import time
import getopt

default_timer = time.time

# ICMP parameters
ICMP_ECHO = 8 # Echo request (per RFC792)
ICMP_MAX_RECV = 2048 # Max size of incoming buffer

MAX_SLEEP = 1000


def calculate_checksum(source_string):
	"""
	A port of the functionality of in_cksum() from ping.c
	Ideally this would act on the string as a series of 16-bit ints (host
	packed), but this works.
	Network data is big-endian, hosts are typically little-endian
	"""
	countTo = (int(len(source_string) / 2)) * 2
	sum = 0
	count = 0

	# Handle bytes in pairs
	while count < countTo:
		if (sys.byteorder == "little"):
			loByte = source_string[count]
			hiByte = source_string[count + 1]
		else:
			loByte = source_string[count + 1]
			hiByte = source_string[count]
		sum += hiByte * 256 + loByte
		count += 2

	# Handle last byte if applicable (odd-number of bytes)
	# Endianness should be irrelevant in this case
	if countTo < len(source_string): # Check for odd length
		loByte = source_string[len(source_string) - 1]
		sum += loByte

	sum &= 0xffffffff # Truncate sum to 32 bits (a variance from ping.c, which
					  # uses signed ints, but overflow is unlikely in ping)

	sum = (sum >> 16) + (sum & 0xffff)	# Add high 16 bits to low 16 bits
	sum += (sum >> 16)					# Add carry from above (if any)
	answer = ~sum & 0xffff				# Invert and truncate to 16 bits
	answer = socket.htons(answer)

	return answer

class Traceroute(object):
	def __init__(self, destination, timeout=1000, max_hops=64, packet_size=55):
		self.destination = destination
		self.timeout = timeout
		self.max_hops = max_hops
		self.packet_size = packet_size
		self.own_id = os.getpid() & 0xFFFF

		try:
			self.dest_ip = socket.gethostbyname(self.destination)			
		except socket.gaierror as e:
			self.print_unknown_host(e)
		else:
			self.print_start()

		self.seq_number = 0

	def print_start(self):
		msg = "\nMY-TRACEROUTE: %s (%s): %d hops max, packet size %d" % (self.destination, self.dest_ip, self.max_hops, self.packet_size)
		print(msg)
		msg = f"{"Hop":<5s}{"Host IP":<18s}{"Host name":<50s}{"RTT":<50s}"
		print(msg)

	def print_unknown_host(self, e):
		msg = "\nMY-TRACEROUTE: Unknown host: %s (%s)\n" % (self.destination, e.args[1])
		print(msg)
		sys.exit(-1)

	def header2dict(self, names, struct_format, data):
		unpacked_data = struct.unpack(struct_format, data)
		return dict(zip(names, unpacked_data))

	def run(self, count=3, max_hops=64):
		for ttl in range(1, max_hops + 1):
			n_successes = 0
			host_addr = None
			delays = []

			while True:
				delay, icmp_type, ip = self.do(ttl)
				if icmp_type != 11 and icmp_type != None:
					n_successes += 1
				if ip != None:
					host_addr = ip

				if delay != None:
					delays = [f"{"%.1f ms":<10s}" % (delay)] + delays
				else:
					delays = [f"{"*":<10s}"] + delays

				self.seq_number += 1
				if count and self.seq_number >= count * ttl:
					break

				if delay == None:
					delay = 0

				# Pause for the remainder of the MAX_SLEEP period (if applicable)
				if (MAX_SLEEP > delay):
					time.sleep((MAX_SLEEP - delay) / 1000.0)

			if host_addr == None:
				host_addr = ""
				host_name = ""
			else:
				try:
					host_name = socket.gethostbyaddr(host_addr)[0]
				except socket.error:
					host_name = ""

			delays_str = " ".join(delays)
			msg = f"{ttl:<5d}{host_addr:<18s}{host_name:<50s}{delays_str:<50s}"
			print(msg)

			if n_successes >= count:
				break

	def do(self, ttl):
		"""
		Send one ICMP ECHO_REQUEST and receive the response until self.timeout.
		Returns the RTT, the ICMP type (11 for time-to-live exceeded), and the IP address of the router
		"""
		current_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.getprotobyname("icmp"))
		current_socket.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)

		send_time = self.send_one_ping(current_socket)
		if send_time == None:
			return None, None, None

		receive_time, ip, icmp_header_type = self.receive_one_ping(current_socket)
		current_socket.close()

		if receive_time:
			delay = (receive_time - send_time) * 1000.0
			return delay, icmp_header_type, ip
		
		return None, None, None

	def send_one_ping(self, current_socket):
		"""
		Send one ICMP ECHO_REQUEST
		"""
		# Header is type (8), code (8), checksum (16), id (16), sequence (16)
		checksum = 0

		# Make a dummy header with a 0 checksum.
		header = struct.pack(
			"!BBHHH", ICMP_ECHO, 0, checksum, self.own_id, self.seq_number
		)

		padBytes = []
		startVal = 0x42
		for i in range(startVal, startVal + (self.packet_size)):
			padBytes += [(i & 0xff)]  # Keep chars in the 0-255 range
		data = bytes(padBytes)

		# Calculate the checksum on the data and the dummy header.
		checksum = calculate_checksum(header + data) # Checksum is in network order

		# Now that we have the right checksum, we put that in. It's just easier
		# to make up a new header than to stuff it into the dummy.
		header = struct.pack(
			"!BBHHH", ICMP_ECHO, 0, checksum, self.own_id, self.seq_number
		)

		packet = header + data

		send_time = default_timer()

		try:
			current_socket.sendto(packet, (self.destination, 1)) # Port number is irrelevant for ICMP
		except socket.error as e:
			self.response.output.append("General failure (%s)" % (e.args[1]))
			current_socket.close()
			return

		return send_time

	def receive_one_ping(self, current_socket):
		"""
		Receive the ping from the socket. timeout = in ms
		"""
		timeout = self.timeout / 1000.0

		while True: # Loop while waiting for packet or timeout
			select_start = default_timer()
			inputready, outputready, exceptready = select.select([current_socket], [], [], timeout)
			select_duration = (default_timer() - select_start)
			if inputready == []: # timeout
				return None, 0, 0

			receive_time = default_timer()

			packet_data, address = current_socket.recvfrom(ICMP_MAX_RECV)

			icmp_header = self.header2dict(
				names=[
					"type", "code", "checksum",
					"packet_id", "seq_number"
				],
				struct_format="!BBHHH",
				data=packet_data[20:28]
			)

			ip_header = self.header2dict(
				names=[
					"version", "type", "length",
					"id", "flags", "ttl", "protocol",
					"checksum", "src_ip", "dest_ip"
				],
				struct_format="!BBHHHBBHII",
				data=packet_data[:20]
			)
			ip = socket.inet_ntoa(struct.pack("!I", ip_header["src_ip"]))
			return receive_time, ip, icmp_header["type"]

			timeout = timeout - select_duration
			if timeout <= 0:
				return None, 0, 0

def traceroute(hostname, timeout=1000, count=3, max_hops=64, packet_size=55, *args, **kwargs):
	p = Traceroute(hostname, timeout, max_hops, packet_size, *args, **kwargs)
	return p.run(count, max_hops)

if sys.argv[1] == "-h" or sys.argv[1] == "--help":
	print("usage: my-traceroute.py host [-q nqueries]")
else:
	dest_name = sys.argv[1]
	nqueries = 3

	arguments, values = getopt.getopt(sys.argv[2:], "q:", ["nqueries="])
	for currentArg, currentVal in arguments:
		if currentArg in ("-q", "--nqueries"):
			nqueries = int(currentVal)

	traceroute(dest_name, count=nqueries)
