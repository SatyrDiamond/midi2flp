# SPDX-FileCopyrightText: 2024 SatyrDiamond and happy_minimix
# SPDX-License-Identifier: GPL-3.0-or-later

from io import BytesIO
from midiparser.parser import MidiFile
from midiparser import events
import numpy as np
import struct
import varint
import argparse
import os

totalnotes = 0

parser = argparse.ArgumentParser()
parser.add_argument("input")
args = parser.parse_args()

input_file = args.input

if not os.path.exists(input_file): exit('file not found')

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

print("Loading MIDI File...")
midifile = MidiFile.fromFile(input_file)

tracks_data = [None for x in range(len(midifile.tracks))]
tracknames = [None for x in range(len(midifile.tracks))]

for tnum, miditrack in enumerate(midifile.tracks):
	notes = [[[] for x in range(128)] for x in range(16)]
	numevents = len(miditrack.events)
	totalnotes += numevents
	notebin = np.zeros(numevents, dtype=midid)
	numnote = 0
	curpos = 0
	for msg in miditrack.events:
		curpos += msg.deltaTime
		if type(msg) == events.NoteOnEvent:
			notebin[numnote] = (1, msg.channel, curpos, 0, msg.note, msg.velocity)
			notes[msg.channel][msg.note].append(numnote)
			numnote += 1
		elif type(msg) == events.NoteOffEvent:
			nd = notes[msg.channel][msg.note]
			if nd:
				notenum = nd.pop()
				notebin[notenum][3] = curpos
				notebin[notenum][0] = 2
		elif type(msg) == events.TrackNameEvent: 
			tracknames[tnum] = msg.name
	tracks_data[tnum] = notebin[0:numnote]
	print("Parsed Track: " + str(tnum))

flpout = open('out.flp', 'wb')

data_FLhd = BytesIO()
data_FLhd.write((len(tracks_data)).to_bytes(3, 'big'))
data_FLhd.write(b'\x00')
data_FLhd.write((midifile.ppqn).to_bytes(2, 'little'))

data_FLdt = BytesIO()

make_flevent(data_FLdt, 199, '8.0.0'.encode('utf8') + b'\x00')

make_flevent(data_FLdt, 93, 0)
make_flevent(data_FLdt, 66, 140)
make_flevent(data_FLdt, 67, 1)
make_flevent(data_FLdt, 9, 1)
make_flevent(data_FLdt, 11, 0)
make_flevent(data_FLdt, 80, 0)
make_flevent(data_FLdt, 17, 16)
make_flevent(data_FLdt, 24, 16)
make_flevent(data_FLdt, 18, 4)
make_flevent(data_FLdt, 23, 1)
make_flevent(data_FLdt, 10, 0)

make_flevent(data_FLdt, 65, 1)
make_flevent(data_FLdt, 193, "midi2flp auto generated data".encode('utf8') + b'\x00')

notebin = np.zeros(totalnotes, dtype=flpd)
ID_Plugin_New = np.zeros(24, dtype=np.uint8)
ID_Plugin_New[8] = 2
ID_Plugin_New[16] = 16
ID_Plugin_Parameters = np.zeros(384, dtype=np.uint8)
ID_Plugin_Parameters[0] = 6
for i in range(8,20): ID_Plugin_Parameters[i] = 255
ID_Plugin_Parameters[4] = 0 #Output channel
ID_Plugin_Parameters[29] = 1 #Map note color to MIDI channel
ID_Plugin_Parameters[322] = 255
numnote = 0

for c, t in enumerate(tracks_data):
	make_flevent(data_FLdt, 64, c)
	make_flevent(data_FLdt, 21, 2)
	make_flevent(data_FLdt, 201, 'MIDI Out'.encode('utf8') + b'\x00')
	make_flevent(data_FLdt, 212, ID_Plugin_New.tobytes())
	if tracknames[c]: make_flevent(data_FLdt, 192, tracknames[c].encode('utf8') + b'\x00')
	make_flevent(data_FLdt, 213, ID_Plugin_Parameters.tobytes())

	for state, chan, start, end, key, vol in t:
		flnote = notebin[numnote]
		flnote['pos'] = start
		flnote['flags'] = 16384
		flnote['rack'] = c
		flnote['dur'] = end-start
		flnote['key'] = key
		flnote['chan'] = chan
		flnote['vol'] = vol
		flnote['unk1'] = 120
		flnote['unk3'] = 64
		flnote['unk4'] = 128
		flnote['unk5'] = 128
		numnote += 1
	print("Converted Track: " + str(c))

print("Writing Output File...")
nums = notebin.argsort(order=['pos'])
notebin = notebin[nums]
notebin = notebin[np.where(notebin['unk1']==120)]

make_flevent(data_FLdt, 224, notebin[0:len(notebin)].tobytes())
make_flevent(data_FLdt, 129, 65536)

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
