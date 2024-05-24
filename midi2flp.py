from io import BytesIO
from mido import MidiFile
from rich.progress import Progress
import numpy as np
import struct
import threading
import varint
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument("input")
args = parser.parse_args()

input_file = args.input

if not os.path.exists(input_file): print('file not found')

midid = np.dtype([('state', np.int8),('chan', np.int8),('start', np.int32),('end', np.int32),('key', np.int8),('vol', np.int8)]) 
flpd = np.dtype([('pos', np.uint32),('flags', np.uint16),('rack', np.uint16),('dur', np.uint32),('key', np.uint8),('unk1', np.uint8),('unk2', np.uint8),('chan', np.uint8),('unk3', np.uint8),('vol', np.uint8),('unk4', np.uint8),('unk5', np.uint8),]) 

def make_flevent(FLdt_bytes, value, data):
	if value <= 63 and value >= 0: # int8
		FLdt_bytes.write(value.to_bytes(1, "little"))
		FLdt_bytes.write(data.to_bytes(1, "little"))
	if value <= 127 and value >= 64 : # int16
		FLdt_bytes.write(value.to_bytes(1, "little"))
		FLdt_bytes.write(data.to_bytes(2, "little"))
	if value <= 191 and value >= 128 : # int32
		FLdt_bytes.write(value.to_bytes(1, "little"))
		FLdt_bytes.write(data.to_bytes(4, "little"))
	if value <= 224 and value >= 192 : # text
		FLdt_bytes.write(value.to_bytes(1, "little"))
		FLdt_bytes.write(varint.encode(len(data)))
		FLdt_bytes.write(data)
	if value <= 255 and value >= 225 : # data
		FLdt_bytes.write(value.to_bytes(1, "little"))
		FLdt_bytes.write(varint.encode(len(data)))
		FLdt_bytes.write(data)

def do_track(tnum, miditrack, progress):
	global tracks_data
	global tracknames
	notes = [[[] for x in range(128)] for x in range(16)]
	numevents = len(miditrack)
	track_progress = progress.add_task("Track "+str(tnum), total=numevents)
	notebin = np.zeros(numevents, dtype=midid)
	numnote = 0
	curpos = 0
	for msg in miditrack:
		curpos += msg.time
		if msg.type == 'note_on' and msg.velocity != 0:
			notebin[numnote] = (1, msg.channel, curpos, 0, msg.note, msg.velocity)
			notes[msg.channel][msg.note].append(numnote)
			numnote += 1
		elif msg.type == 'note_on' and msg.velocity == 0:
			nd = notes[msg.channel][msg.note]
			if nd:
				notenum = nd.pop()
				notebin[notenum][3] = curpos
				notebin[notenum][0] = 2
		elif msg.type == 'note_off':
			nd = notes[msg.channel][msg.note]
			if nd:
				notenum = nd.pop()
				notebin[notenum][3] = curpos
				notebin[notenum][0] = 2
		elif msg.type == 'track_name': 
			tracknames[tnum] = msg.name
		progress.update(track_progress, advance=1)
	tracks_data[tnum] = notebin[1:numnote+1]


midifile = MidiFile(input_file)

tracks_data = [None for x in range(len(midifile.tracks))]
tracknames = [None for x in range(len(midifile.tracks))]

with Progress() as progress:
	for n, x in enumerate(midifile.tracks):
		td = threading.Thread(target=do_track, args=(n, x, progress))
		td.start()
	while not progress.finished: pass

flpout = open('out.flp', 'wb')

data_FLhd = BytesIO()
data_FLhd.write((len(tracks_data)).to_bytes(3, 'big'))
data_FLhd.write(b'\x00')
data_FLhd.write((midifile.ticks_per_beat).to_bytes(2, 'little'))

data_FLdt = BytesIO()

make_flevent(data_FLdt, 199, '8.0.0'.encode('utf8') + b'\x00')

make_flevent(data_FLdt, 93, 0)
make_flevent(data_FLdt, 66, 140)
make_flevent(data_FLdt, 67, 1)
make_flevent(data_FLdt, 9, 1)
make_flevent(data_FLdt, 11, 0)
make_flevent(data_FLdt, 12, 128)
make_flevent(data_FLdt, 80, 0)
make_flevent(data_FLdt, 17, 16)
make_flevent(data_FLdt, 24, 16)
make_flevent(data_FLdt, 18, 4)
make_flevent(data_FLdt, 23, 1)
make_flevent(data_FLdt, 10, 0)

for c, t in enumerate(tracks_data):
	make_flevent(data_FLdt, 64, c)
	if tracknames[c]: make_flevent(data_FLdt, 192, tracknames[c].encode('utf8') + b'\x00')
	make_flevent(data_FLdt, 65, c+1)
	if tracknames[c]: make_flevent(data_FLdt, 193, tracknames[c].encode('utf8') + b'\x00')

	notebin = np.zeros(len(t), dtype=flpd)
	invalid = 0
	numnote = 0
	for state, chan, start, end, key, vol in t:
		if state == 2: 
			flnote = notebin[numnote]
			flnote['pos'] = start
			flnote['flags'] = 16384
			flnote['rack'] = c
			flnote['dur'] = end-start
			flnote['key'] = key
			flnote['chan'] = chan
			flnote['vol'] = vol
			flnote['unk3'] = 64
			flnote['unk4'] = 128
			flnote['unk5'] = 128
			numnote += 1
		else: 
			invalid += 1

	make_flevent(data_FLdt, 224, notebin[0:len(notebin)-invalid].tobytes())
	make_flevent(data_FLdt, 129, 65536*(c+1))

data_FLhd.seek(0)
flpout.write(b'FLhd')
data_FLhd_out = data_FLhd.read()
flpout.write(len(data_FLhd_out).to_bytes(4, 'little'))
flpout.write(data_FLhd_out)

data_FLdt.seek(0)
flpout.write(b'FLdt')
data_FLdt_out = data_FLdt.read()
flpout.write(len(data_FLdt_out).to_bytes(4, 'little'))
flpout.write(data_FLdt_out)

