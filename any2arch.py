#!/usr/bin/env python3

#
# Copyright (c) 2013 Christopher Atherton. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#

import argparse
import datetime
import fractions
import glob
import math
import multiprocessing
import os
import re
import subprocess
import tempfile
import time

process_start_time = time.time()

# Parse command line
command_line_parser = argparse.ArgumentParser( description='Convert videos to archive format.' )
command_line_parser.add_argument( 'input', help='Input video file', metavar='FILE' )
command_line_parser.add_argument( '-o', '--output', required=True, help='Path for output file', metavar='FILE' )
command_line_parser.add_argument( '-H', '--high-quality', action='store_true', help='Use higher quality settings' )
command_line_parser.add_argument( '--start-chapter', type=int, help='Start at specific chapter', metavar='NUM' )
command_line_parser.add_argument( '--end-chapter', type=int, help='Stop at specific chapter', metavar='NUM' )

command_line_metadata_group = command_line_parser.add_argument_group( 'metadata' )
command_line_metadata_group.add_argument( '-t', '--title', help='Specify a title for the video' )
command_line_metadata_group.add_argument( '-V', '--video-language', help='Specify the language for the video', metavar='LANG' )
command_line_metadata_group.add_argument( '-A', '--audio-language', help='Specify the language for the audio', metavar='LANG' )
command_line_metadata_group.add_argument( '-S', '--subtitles-language', help='Specify the language for the subtitles', metavar='LANG' )

command_line_disc_group = command_line_parser.add_argument_group( 'disc' )
command_line_disc_mutex_group = command_line_disc_group.add_mutually_exclusive_group()
command_line_disc_mutex_group.add_argument( '-D', '--dvd', action='store_true', help='Indicate that the soure is a DVD' )
command_line_disc_mutex_group.add_argument( '-B', '--bluray', action='store_true', help='Indicate that the soure is a Blu-ray' )
command_line_disc_group.add_argument( '-T', '--disc-title', default=1, type=int, help='Specify disc title number', metavar='NUM' )
command_line_disc_group.add_argument( '-Z', '--size', nargs=2, type=int, help='Force input display dimensions (required for --bluray)', metavar=( 'W', 'H' ) )
command_line_disc_group.add_argument( '-R', '--rate', nargs=2, type=int, help='Force input frame rate (required for --bluray and progressive --dvd)', metavar=( 'N', 'D' ) )

command_line_picture_group = command_line_parser.add_argument_group( 'picture' )
command_line_picture_group.add_argument( '-d', '--deinterlace', action='store_true', help='Perform deinterlacing' )
command_line_picture_group.add_argument( '-i', '--ivtc', action='store_true', help='Perform inverse telecine' )
command_line_picture_group.add_argument( '-c', '--crop', nargs=4, type=int, help='Crop the picture', metavar=( 'W', 'H', 'X', 'Y' ) )
command_line_picture_group.add_argument( '-s', '--scale', nargs=2, type=int, help='Scale the picture', metavar=( 'W', 'H' ) )
command_line_picture_aspect_group = command_line_picture_group.add_mutually_exclusive_group()
command_line_picture_aspect_group.add_argument( '-a', '--display-aspect', nargs=2, type=int, help='Specify the display aspect of the picture', metavar=( 'W', 'H' ) )
command_line_picture_aspect_group.add_argument( '-p', '--pixel-aspect', nargs=2, type=int, help='Specify the display pixel aspect of the picture', metavar=( 'W', 'H' ) )
command_line_picture_aspect_group.add_argument( '-z', '--display-size', nargs=2, type=int, help='Specify the display dimensions of the picture', metavar=( 'W', 'H' ) )

command_line_other_group = command_line_parser.add_argument_group( 'other' )
command_line_other_group.add_argument( '--no-nice', action='store_true', help='Do not lower process priority' )
command_line_other_group.add_argument( '--no-chapters', action='store_true', help='Do not include chapters from DVD/Matroska source' )
command_line_other_group.add_argument( '--no-attachments', action='store_true', help='Do not include attachments from Matroska source' )

command_line = command_line_parser.parse_args()

# Verify command line sanity
if command_line.bluray:
	if not command_line.size:
		print( 'ERROR: You must manually input the size of the input for Blu-ray sources!' )
		exit( 1 )
	if not command_line.rate:
		print( 'ERROR: You must manually input the frame rate of the input for Blu-ray sources!' )
		exit( 1 )

# Reduce priority
if not command_line.no_nice:
	os.nice( 10 )

# Begin processing
print( 'Processing ' + os.path.basename( command_line.input ) + ' ...' )

# Generate MPlayer input arguments
if command_line.dvd:
	mplayer_input_args = [ '-dvd-device', command_line.input, 'dvd://' + str( command_line.disc_title ) ]
elif command_line.bluray:
	mplayer_input_args = [ '-bluray-device', command_line.input, 'bluray://' + str( command_line.disc_title ) ]
else:
	mplayer_input_args = [ command_line.input ]
if command_line.start_chapter:
	mplayer_input_args.append( '-chapter' )
	if command_line.end_chapter:
		mplayer_input_args.append( str( command_line.start_chapter ) + '-' + str( command_line.end_chapter ) )
	else:
		mplayer_input_args.append( str( command_line.start_chapter ) )
elif command_line.end_chapter:
	mplayer_input_args.append( '-chapter' )
	mplayer_input_args.append( '-' + str( command_line.end_chapter ) )

# Probe input file
mplayer_probe_output = subprocess.check_output( [ 'mplayer', '-nocorrect-pts', '-vo', 'null', '-ac', 'ffmp3,', '-ao', 'null', '-endpos', '0' ] + mplayer_input_args, stderr=subprocess.DEVNULL ).decode()
video_spec_mat = re.search( r'^VIDEO:  \[?(\w+)\]?  (\d+)x(\d+) .+ (\d+\.\d+) fps', mplayer_probe_output, re.M )
audio_spec_mat = re.search( r'^AUDIO: (\d+) Hz, (\d+) ch', mplayer_probe_output, re.M )
audio_codec_mat = re.search( r'^Selected audio codec: \[(\w+)\]', mplayer_probe_output, re.M )

in_ismatroska = os.path.splitext( command_line.input )[1].lower() == '.mkv'
if in_ismatroska:
	mkvmerge_probe_output = subprocess.check_output( [ 'mkvmerge', '-i', command_line.input ], stderr=subprocess.DEVNULL ).decode()

# Create work directory
work_dir = tempfile.TemporaryDirectory( prefix='any2arch-' )
print( 'Created work directory: ' + work_dir.name + ' ...' )

# Extract chapters
if not command_line.no_chapters:
	if in_ismatroska:
		haschapters = mkvmerge_probe_output.find( 'Chapters: ' ) != -1
		if haschapters:
			print( 'Extracting chapters ...' )
			chapters = subprocess.check_output( [ 'mkvextract', 'chapters', command_line.input, '-s' ], stderr=subprocess.DEVNULL ).decode()
	elif command_line.dvd:
		haschapters = True
		print( 'Extracting chapters ...' )
		chapters = subprocess.check_output( [ 'dvdxchap', '-t', str( command_line.disc_title ), command_line.input ], stderr=subprocess.DEVNULL ).decode()
	else:
		haschapters = False

	if haschapters:
		if command_line.start_chapter or command_line.end_chapter:
			new_chapters = str()
			if command_line.start_chapter:
				chapters_offset_index = command_line.start_chapter - 1
				mat = re.search( r'^CHAPTER' + str( command_line.start_chapter ).zfill( 2 ) + r'=(\d\d):(\d\d):(\d\d)\.(\d\d\d)$', chapters, re.M )
				if not mat:
					print( 'ERROR: Start chapter could not be found!' )
					exit( 1 )
				chapters_offset_time = datetime.timedelta( hours=int( mat.group( 1 ) ), minutes=int( mat.group( 2 ) ), seconds=int( mat.group( 3 ) ), milliseconds=int( mat.group( 4 ) ) )
			else:
				chapters_offset_index = 0
				chapters_offset_time = datetime.timedelta()
			for line in chapters.splitlines():
				mat = re.match( r'^CHAPTER(\d+)=(\d\d):(\d\d):(\d\d)\.(\d\d\d)$', line )
				if mat and ( not command_line.start_chapter or int( mat.group( 1 ) ) >= command_line.start_chapter ) and ( not command_line.end_chapter or int( mat.group( 1 ) ) <= command_line.end_chapter ):
					new_time = datetime.timedelta( hours=int( mat.group( 2 ) ), minutes=int( mat.group( 3 ) ), seconds=int( mat.group( 4 ) ), milliseconds=int( mat.group( 5 ) ) ) - chapters_offset_time
					new_chapters += 'CHAPTER' + str( int( mat.group( 1 ) ) - chapters_offset_index ).zfill( 2 ) + '='
					new_time_hours = math.floor( new_time.total_seconds() / 3600 )
					new_chapters += str( new_time_hours ).zfill( 2 ) + ':'
					new_time_minutes = math.floor( ( new_time.total_seconds() - new_time_hours * 3600 ) / 60 )
					new_chapters += str( new_time_minutes ).zfill( 2 ) + ':'
					new_time_seconds = math.floor( new_time.total_seconds() - new_time_hours * 3600 - new_time_minutes * 60 )
					new_chapters += str( new_time_seconds ).zfill( 2 ) + '.'
					new_time_milliseconds = round( ( new_time.total_seconds() - new_time_hours * 3600 - new_time_minutes * 60 - new_time_seconds ) * 1000 )
					new_chapters += str( new_time_milliseconds ).zfill( 2 ) + os.linesep
				else:
					mat = re.match( r'CHAPTER(\d+)NAME=Chapter (\d+)$', line )
					if mat and ( not command_line.start_chapter or int( mat.group( 1 ) ) >= command_line.start_chapter ) and ( not command_line.end_chapter or int( mat.group( 1 ) ) <= command_line.end_chapter ):
						new_chapters += 'CHAPTER' + str( int( mat.group( 1 ) ) - chapters_offset_index ).zfill( 2 ) + 'NAME=Chapter ' + str( int( mat.group( 2 ) ) - chapters_offset_index ).zfill( 2 ) + os.linesep
					else:
						mat = re.match( r'CHAPTER(\d+)NAME=(.*)$', line )
						if mat and ( not command_line.start_chapter or int( mat.group( 1 ) ) >= command_line.start_chapter ) and ( not command_line.end_chapter or int( mat.group( 1 ) ) <= command_line.end_chapter ):
							new_chapters += 'CHAPTER' + str( int( mat.group( 1 ) ) - chapters_offset_index ).zfill( 2 ) + 'NAME=' + mat.group( 2 )
			chapters = new_chapters
		chapters_path = os.path.join( work_dir.name, 'chapters' )
		with open( chapters_path, 'w' ) as chapters_file:
			chapters_file.write( chapters )
	elif command_line.start_chapter or command_line.end_chapter:
		print( 'ERROR: No chapters available for --start-chapter or --end-chapter!' )
		exit( 1 )
else:
	haschapters = False

# Extract attachments
if not command_line.no_attachments and in_ismatroska:
	attachmentcnt = mkvmerge_probe_output.count( 'Attachment ID ' )
	if attachmentcnt > 0:
		print( 'Extracting ' + str( attachmentcnt ) + ' attachment(s) ...' )
		attachments_path = os.path.join( work_dir.name, 'attachments' )
		in_path = os.path.abspath( command_line.input )
		cwd = os.getcwd()
		os.mkdir( attachments_path )
		os.chdir( attachments_path )
		subprocess.check_call( [ 'mkvextract', 'attachments', in_path ] + list( map( str, range( 1, attachmentcnt + 1 ) ) ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
		os.chdir( cwd )
else:
	attachmentcnt = 0

# Extract subtitles
if in_ismatroska:
	subtitle_mat = re.search( r'^Track ID (\d+): subtitles', mkvmerge_probe_output, re.M )
	if subtitle_mat is not None:
		hassubtitles = True
		if mkvmerge_probe_output.count( ' subtitles ' ) > 1:
			print( 'WARNING: Source has multiple subtitle tracks!' )
		print( 'Extracting subtitles ...' )
		subtitles_path = os.path.join( work_dir.name, 'subtitles' )
		subprocess.check_call( [ 'mkvextract', 'tracks', command_line.input, subtitle_mat.group( 1 ) + ':' + subtitles_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
	else:
		hassubtitles = False
else:
	hassubtitles = False

# Decode/extract/encode audio
if in_ismatroska and mkvmerge_probe_output.count( ' audio ' ) > 1:
	print( 'WARNING: Source has multiple audio tracks!' )
if audio_codec_mat.group( 1 ) == 'ffvorbis' and in_ismatroska and not command_line.start_chapter and not command_line.end_chapter:
	print( 'Extracting Vorbis audio ...' )
	ogg_audio_path = os.path.join( work_dir.name, 'audio.ogg' )
	
	subprocess.check_call( [ 'mkvextract', 'tracks', command_line.input, re.search( r'^Track ID (\d+): audio \((.+)\)', mkvmerge_probe_output, re.M ).group( 1 ) + ':' + ogg_audio_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
elif audio_codec_mat.group( 1 ) == 'ffflac' and in_ismatroska and not command_line.start_chapter and not command_line.end_chapter:
	print( 'Extracting FLAC audio ...' )
	flac_audio_path = os.path.join( work_dir.name, 'audio.flac' )
	subprocess.check_call( [ 'mkvextract', 'tracks', command_line.input, re.search( r'^Track ID (\d+): audio \((.+)\)', mkvmerge_probe_output, re.M ).group( 1 ) + ':' + flac_audio_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

	print( 'Encoding audio ...' )
	enc_audio_path = os.path.join( work_dir.name, 'audio.ogg' )
	subprocess.check_call( [ 'oggenc', '--ignorelength', '--discard-comments', '-o', enc_audio_path, flac_audio_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
elif audio_codec_mat.group( 1 ) == 'ffaac' and in_ismatroska and not command_line.start_chapter and not command_line.end_chapter:
	print( 'Extracting AAC audio ...' )
	aac_audio_path = os.path.join( work_dir.name, 'audio.m4a' )
	subprocess.check_call( [ 'mkvextract', 'tracks', command_line.input, re.search( r'^Track ID (\d+): audio \((.+)\)', mkvmerge_probe_output, re.M ).group( 1 ) + ':' + aac_audio_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

	print( 'Decoding AAC audio ...' )
	dec_audio_path = os.path.join( work_dir.name, 'audio.wav' )
	subprocess.check_call( [ 'faad', '-b', '4', '-o', dec_audio_path, aac_audio_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

	print( 'Encoding audio ...' )
	enc_audio_path = os.path.join( work_dir.name, 'audio.ogg' )
	subprocess.check_call( [ 'oggenc', '--ignorelength', '-o', enc_audio_path, dec_audio_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
else:
	print( 'Decoding audio ...' )
	dec_audio_path = os.path.join( work_dir.name, 'audio.wav' )
	subprocess.check_call( [ 'mplayer', '-nocorrect-pts', '-vc', 'null', '-vo', 'null', '-channels', audio_spec_mat.group( 2 ), '-ao', 'pcm:fast:file=' + dec_audio_path ] + mplayer_input_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

	print( 'Encoding audio ...' )
	enc_audio_path = os.path.join( work_dir.name, 'audio.ogg' )
	subprocess.check_call( [ 'oggenc', '--ignorelength', '-o', enc_audio_path, dec_audio_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

# Compute output video format
if command_line.scale:
	out_video_dimensions = command_line.scale
elif command_line.crop:
	out_video_dimensions = command_line.crop[0:2]
elif command_line.size:
	out_video_dimensions = command_line.size
else:
	out_video_dimensions = [ int( video_spec_mat.group( 2 ) ), int( video_spec_mat.group( 3 ) ) ]
if command_line.ivtc:
	out_video_framerate_frac = [ 24000, 1001 ]
	out_video_framerate_float = 24000.0 / 1001.0
elif command_line.rate:
	out_video_framerate_frac = command_line.rate
	out_video_framerate_float = float( out_video_framerate_frac[0] ) / float( out_video_framerate_frac[1] )
else:
	out_video_framerate_float = float( video_spec_mat.group( 4 ) )
	if abs( math.ceil( out_video_framerate_float ) / 1.001 - out_video_framerate_float ) / out_video_framerate_float < 0.00001:
		out_video_framerate_frac = [ math.ceil( out_video_framerate_float ) * 1000, 1001 ]
		out_video_framerate_float = float( out_video_framerate_frac[0] ) / float( out_video_framerate_frac[1] )
	else:
		out_video_framerate_frac = fractions.Fraction( out_video_framerate_float )
		out_video_framerate_frac = [ out_video_framerate_frac.numerator, out_video_framerate_frac.denominator ]
if command_line.deinterlace and not command_line.ivtc:
	out_video_framerate_frac = fractions.Fraction( 2*out_video_framerate_frac[0], out_video_framerate_frac[1] )
	out_video_framerate_frac = [ out_video_framerate_frac.numerator, out_video_framerate_frac.denominator ]
	out_video_framerate_float = float( out_video_framerate_frac[0] ) / float( out_video_framerate_frac[1] )

# Generate decoder settings
filters = 'format=i420,'
if command_line.ivtc:
	filters += 'pullup,softskip,'
	ofps = [ '-ofps', '24000/1001' ]
elif command_line.rate:
	ofps = [ '-ofps', '/'.join( map( str, command_line.rate ) ) ]
else:
	ofps = list()
if command_line.deinterlace:
	filters += 'yadif=1,'
if command_line.crop:
	filters += 'crop=' + ':'.join( map( str, command_line.crop ) ) + ','
if command_line.scale:
	filters += 'scale=' + ':'.join( map( str, command_line.scale ) ) + ','
filters += 'hqdn3d,harddup'

# Generate encoder settings
if command_line.high_quality:
	bitrate = '3200'
	cq_level = '1'
else:
	bitrate = '1700'
	cq_level = '4'
if out_video_dimensions[1] < 480:
	token_parts = '0'
elif out_video_dimensions[1] < 720:
	token_parts = '1'
elif out_video_dimensions[1] < 1080:
	token_parts = '2'
else:
	token_parts = '3'
kf_max_dist = str( math.floor( out_video_framerate_float * 10.0 ) )

# Encode video - Pass 1
print( 'Encoding video (pass 1) ...' )
enc_stats_path = os.path.join( work_dir.name, 'vpx_stats' )
dec_proc = subprocess.Popen( [ 'mencoder', '-quiet', '-really-quiet', '-nosound', '-nosub', '-sws', '9', '-vf', filters ] + ofps + [ '-ovc', 'raw', '-of', 'rawvideo', '-o', '-' ] + mplayer_input_args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL )
enc_proc = subprocess.Popen( [ 'vpxenc', '--passes=2', '--pass=1', '--fpf=' + enc_stats_path, '--threads=' + str( multiprocessing.cpu_count() ), '--best', '--lag-in-frames=16', '--end-usage=cq', '--target-bitrate=' + bitrate, '--min-q=0', '--max-q=24', '--auto-alt-ref=1', '--token-parts=' + token_parts, '--cq-level=' + cq_level, '--kf-max-dist=' + kf_max_dist, '--i420', '--fps=' + str( out_video_framerate_frac[0] ) + '/' + str( out_video_framerate_frac[1] ), '--width=' + str( out_video_dimensions[0] ), '--height=' + str( out_video_dimensions[1] ), '--ivf', '--output=' + os.devnull, '-' ], stdin=dec_proc.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
dec_proc.stdout.close()
if dec_proc.wait():
	print( 'ERROR: Error occurred in decoding process!' )
	exit( 1 )
if enc_proc.wait():
	print( 'ERROR: Error occurred in encoding process!' )
	exit( 1 )

# Encode video - Pass 2
print( 'Encoding video (pass 2) ...' )
enc_video_path = os.path.join( work_dir.name, 'video.ivf' )
dec_proc = subprocess.Popen( [ 'mencoder', '-quiet', '-really-quiet', '-nosound', '-nosub', '-sws', '9', '-vf', filters ] + ofps + [ '-ovc', 'raw', '-of', 'rawvideo', '-o', '-' ] + mplayer_input_args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL )
enc_proc = subprocess.Popen( [ 'vpxenc', '--passes=2', '--pass=2', '--fpf=' + enc_stats_path, '--threads=' + str( multiprocessing.cpu_count() ), '--best', '--lag-in-frames=16', '--end-usage=cq', '--target-bitrate=' + bitrate, '--min-q=0', '--max-q=24', '--auto-alt-ref=1', '--token-parts=' + token_parts, '--cq-level=' + cq_level, '--kf-max-dist=' + kf_max_dist, '--i420', '--fps=' + str( out_video_framerate_frac[0] ) + '/' + str( out_video_framerate_frac[1] ), '--width=' + str( out_video_dimensions[0] ), '--height=' + str( out_video_dimensions[1] ), '--ivf', '--output=' + enc_video_path, '-' ], stdin=dec_proc.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
dec_proc.stdout.close()
if dec_proc.wait():
	print( 'ERROR: Error occurred in decoding process!' )
	exit( 1 )
if enc_proc.wait():
	print( 'ERROR: Error occurred in encoding process!' )
	exit( 1 )

# Mux
print( 'Muxing ...' )
mux_cmd = [ 'mkvmerge' ]
if command_line.title:
	mux_cmd.append( '--title' )
	mux_cmd.append( command_line.title )
if haschapters:
	mux_cmd.append( '--chapters' )
	mux_cmd.append( chapters_path )
if attachmentcnt > 0:
	for i in sorted( glob.glob( os.path.join( attachments_path, '*' ) ) ):
		mux_cmd.append( '--attach-file' )
		mux_cmd.append( i )
mux_cmd.append( '--output' )
mux_cmd.append( command_line.output )
if command_line.video_language:
	mux_cmd.append( '--language' )
	mux_cmd.append( '0:' + command_line.video_language )
if command_line.display_aspect:
	mux_cmd.append( '--aspect-ratio' )
	mux_cmd.append( '0:' + str( command_line.display_aspect[0] ) + '/' + str( command_line.display_aspect[1] ) )
if command_line.pixel_aspect:
	mux_cmd.append( '--aspect-ratio-factor' )
	mux_cmd.append( '0:' + str( command_line.pixel_aspect[0] ) + '/' + str( command_line.pixel_aspect[1] ) )
if command_line.display_size:
	mux_cmd.append( '--display-dimensions' )
	mux_cmd.append( '0:' + str( command_line.display_size[0] ) + 'x' + str( command_line.display_size[1] ) )
mux_cmd.append( enc_video_path )
if command_line.audio_language:
	mux_cmd.append( '--language' )
	mux_cmd.append( '0:' + command_line.audio_language )
mux_cmd.append( enc_audio_path )
if hassubtitles:
	if command_line.subtitles_language:
		mux_cmd.append( '--language' )
		mux_cmd.append( '0:' + command_line.subtitles_language )
	mux_cmd.append( subtitles_path )
subprocess.check_call( mux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

# Clean up
print( 'Cleaning up ...' )
work_dir.cleanup()

# Done
if not command_line.bluray:
	print( 'File size ratio: ' + str( round( float( os.path.getsize( command_line.output ) ) / float( os.path.getsize( command_line.input ) ), 3 ) ) )
print( 'Done. Process took ' + str( round( time.time() - process_start_time ) ) + ' seconds.' )
