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
import fractions
import glob
import math
import multiprocessing
import os
import re
import subprocess
import sys
import tempfile
import time

class AVFile:
	EXTS = [ '.avi', '.mkv', '.mp4', '.mpg', '.ts' ]

	EXT_CONTAINER_MAP = {
		'.asf' : 'Advanced Systems Format',
		'.avi' : 'Audio Video Interleave',
		'.mkv' : 'Matroska',
		'.mp4' : 'MP4',
		'.mpg' : 'MPEG Program Stream',
		'.ts'  : 'MPEG Transport Stream',
		'.wmv' : 'Advanced Systems Format'
	}

	MPLAYER_CODEC_MAP = {
		'ffaac' : 'AAC',
		'ffac3' : 'AC-3',
		'ffflac' : 'FLAC',
		'ffh264' : 'H.264',
		'fflpcm' : 'PCM',
		'ffmpeg1' : 'MPEG-1',
		'ffmpeg2' : 'MPEG-2',
		'ffvorbis' : 'Vorbis',
		'ffvp8' : 'VP8',
		'mpg123' : 'MP3'
	}

	MKVMERGE_SUBTITLE_MAP = {
		'S_TEXT/ASS' : 'ASS',
		'S_TEXT/UTF8' : 'SRT'
	}

	mplayer_probe_video_spec_re = re.compile( r'^VIDEO:  \[?(\w+)\]?  (\d+)x(\d+) .+ (\d+\.\d+) fps', re.M )
	mplayer_probe_video_codec_re = re.compile( r'^Selected video codec: \[(\w+)\]', re.M )
	mplayer_probe_audio_spec_re = re.compile( r'^AUDIO: (\d+) Hz, (\d+) ch', re.M )
	mplayer_probe_audio_codec_re = re.compile( r'^Selected audio codec: \[(\w+)\]', re.M )
	mkvmerge_probe_audio_re = re.compile( r'^Track ID (\d+): audio \((.+)\)', re.M )
	mkvmerge_probe_subtitles_re = re.compile( r'^Track ID (\d+): subtitles \((.+)\)$', re.M )

	def __init__( self, path, disc_type=None, disc_title=1, size=None, rate=None ):
		self.path = os.path.abspath( path )

		if disc_type == 'bluray':
			self.mplayer_input_args = [ '-bluray-device', self.path, 'bluray://' + str( disc_title ) ]
			self.disc_title = disc_title
			self.container_format = 'Blu-ray'
			self.has_chapters = False
			self.has_subtitles = False
			self.attachment_count = 0
		elif disc_type == 'dvd':
			self.mplayer_input_args = [ '-dvd-device', self.path, 'dvd://' + str( disc_title ) ]
			self.disc_title = disc_title
			self.container_format = 'DVD'
			self.has_chapters = True
			self.has_subtitles = False
			self.attachment_count = 0
			# TODO Extract dvd subtitles
		else:
			self.mplayer_input_args = [ self.path ]
			self.container_format = self.EXT_CONTAINER_MAP[ os.path.splitext( path )[1] ]
			
			if self.container_format == 'Matroska':
				# mkvmerge probe
				mkvmerge_probe_output = subprocess.check_output( [ 'mkvmerge', '-i', path ] ).decode()
				audio_mat = self.mkvmerge_probe_audio_re.search( mkvmerge_probe_output )
				subtitles_mat = self.mkvmerge_probe_subtitles_re.search( mkvmerge_probe_output )

				self.has_chapters = mkvmerge_probe_output.find( 'Chapters' ) != -1
				if audio_mat.group( 2 ) == 'A_VORBIS' or audio_mat.group( 2 ) == 'A_FLAC' or audio_mat.group( 2 ) == 'A_AAC':
					self.audio_track_id = int( audio_mat.group( 1 ) )
				if subtitles_mat is not None:
					self.has_subtitles = True
					self.subtitles_track_id = int( subtitles_mat.group( 1 ) )
					self.subtitles_type = self.MKVMERGE_SUBTITLE_MAP[ subtitles_mat.group( 2 ) ]
				else:
					self.has_subtitles = False
				self.attachment_count = mkvmerge_probe_output.count( 'Attachment ID' )
			else:
				self.has_chapters = False
				self.has_subtitles = False
				self.attachment_count = 0

		# MPlayer probe
		mplayer_probe_output = subprocess.check_output( [ 'mplayer', '-nocorrect-pts', '-vo', 'null', '-ao', 'null', '-endpos', '0' ] + self.mplayer_input_args, stderr=subprocess.DEVNULL ).decode()
		video_spec_mat = self.mplayer_probe_video_spec_re.search( mplayer_probe_output )
		video_codec_mat = self.mplayer_probe_video_codec_re.search( mplayer_probe_output )
		audio_spec_mat = self.mplayer_probe_audio_spec_re.search( mplayer_probe_output )
		audio_codec_mat = self.mplayer_probe_audio_codec_re.search( mplayer_probe_output )

		# Get video and audio formats
		self.video_format = self.MPLAYER_CODEC_MAP[ video_codec_mat.group( 1 ) ]
		self.audio_format = self.MPLAYER_CODEC_MAP[ audio_codec_mat.group( 1 ) ]

		# Get video size and frame rate
		if disc_type != 'bluray':
			self.video_dimensions = [ int( video_spec_mat.group( 2 ) ), int( video_spec_mat.group( 3 ) ) ]
			self.video_framerate_float = float( video_spec_mat.group( 4 ) )
			if abs( math.ceil( self.video_framerate_float ) / 1.001 - self.video_framerate_float ) / self.video_framerate_float < 0.00001:
				self.video_framerate_frac = [ math.ceil( self.video_framerate_float ) * 1000, 1001 ]
			else:
				video_framerate_frac2 = fractions.Fraction( self.video_framerate_float )
				self.video_framerate_frac = [ video_framerate_frac2.numerator, video_framerate_frac2.denominator ]
			self.video_framerate_float = float( self.video_framerate_frac[0] ) / float( self.video_framerate_frac[1] )
		if size is not None:
			self.video_dimensions = size
		if rate is not None:
			self.video_framerate_frac = rate
			self.video_framerate_float = float( rate[0] ) / float( rate[1] )

		# Get audio sample rate and channel count
		self.audio_samplerate = int( audio_spec_mat.group( 1 ) )
		self.audio_channelcnt = int( audio_spec_mat.group( 2 ) )

	def extract_chapters( self, path ):
		assert self.has_chapters
		chapters_file = open( path, 'w' )
		if self.container_format == 'Matroska':
			subprocess.check_call( [ 'mkvextract', 'chapters', self.path, '-s' ], stdout=chapters_file, stderr=subprocess.DEVNULL )
		elif self.container_format == 'DVD':
			subprocess.check_call( [ 'dvdxchap', '-t', str( self.disc_title ), self.path ], stdout=chapters_file, stderr=subprocess.DEVNULL )
		chapters_file.close()

	def extract_subtitles( self, path ):
		assert self.has_subtitles
		if self.container_format == 'Matroska':
			subprocess.check_call( [ 'mkvextract', 'tracks', self.path, str( self.subtitles_track_id ) + ':' + path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

	def extract_attachments( self, path ):
		assert self.attachment_count > 0
		if self.container_format == 'Matroska':
			old_cwd = os.getcwd()
			os.mkdir( path )
			os.chdir( path )
			attachment_ids = []
			for i in range( self.attachment_count ):
				attachment_ids.append( str( i + 1 ) )
			subprocess.check_call( [ 'mkvextract', 'attachments', self.path ] + attachment_ids, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
			os.chdir( old_cwd )

	def extract_audio( self, path ):
		assert self.container_format == 'Matroska'
		assert self.audio_format == 'Vorbis' or self.audio_format == 'FLAC' or self.audio_format == 'AAC'
		if self.audio_format == 'Vorbis':
			subprocess.check_call( [ 'mkvextract', 'tracks', self.path, str( self.audio_track_id ) + ':' + path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
		elif self.audio_format == 'FLAC':
			subprocess.check_call( [ 'mkvextract', 'tracks', self.path, str( self.audio_track_id ) + ':' + path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
		elif self.audio_format == 'AAC':
			subprocess.check_call( [ 'mkvextract', 'tracks', self.path, str( self.audio_track_id ) + ':' + path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

	def decode_audio( self, path ):
		subprocess.check_call( [ 'mplayer', '-nocorrect-pts', '-vc', 'null', '-vo', 'null', '-channels', str( self.audio_channelcnt ), '-ao', 'pcm:fast:file=' + path ] + self.mplayer_input_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

	def start_decode_video( self, deinterlace=False, ivtc=False, crop=None, scale=None ):
		filters = 'scale,format=i420,'
		if_ofps = []
		if ivtc:
			filters += 'pullup,softskip,'
			if_ofps = [ '-ofps', '24000/1001' ]
		if deinterlace:
			filters += 'yadif=1,'
		if crop:
			filters += 'crop=' + str( crop[0] ) + ':' + str( crop[1] ) + ':' + str( crop[2] ) + ':' + str( crop[3] ) + ','
		if scale:
			filters += 'scale=' + str( scale[0] ) + ':' + str( scale[1] ) + ','
		filters += 'hqdn3d,harddup'
		return subprocess.Popen( [ 'mencoder', '-quiet', '-really-quiet', '-nosound', '-nosub', '-sws', '9', '-vf', filters ] + if_ofps + [ '-ovc', 'raw', '-of', 'rawvideo', '-o', '-' ] + self.mplayer_input_args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL )

def decode_aac_audio( in_path, out_path ):
	subprocess.check_call( [ 'faad', '-b', '4', '-o', out_path, in_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

def decode_flac_audio( in_path, out_path ):
	subprocess.check_call( [ 'flac', '-d', '-o', out_path, in_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

def encode_vorbis_audio( in_path, out_path ):
	subprocess.check_call( [ 'oggenc', '--discard-comments', '-o', out_path, in_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

def start_encode_vp8_video_pass_1( in_pipe, stats_path, dimensions, framerate, high_quality=False ):
	if high_quality:
		bitrate = 3200
		cq_level = 1
	else:
		bitrate = 1700
		cq_level = 4
	if dimensions[1] < 480:
		token_parts = 0
	elif dimensions[1] < 720:
		token_parts = 1
	elif dimensions[1] < 1080:
		token_parts = 2
	else:
		token_parts = 3
	kf_max_dist = math.floor( float( framerate[0] ) / float( framerate[1] ) * 10.0 )
	return subprocess.Popen( [ 'vpxenc', '--passes=2', '--pass=1', '--fpf=' + stats_path, '--threads=' + str( multiprocessing.cpu_count() ), '--best', '--lag-in-frames=16', '--end-usage=cq', '--target-bitrate=' + str( bitrate ), '--min-q=0', '--max-q=24', '--auto-alt-ref=1', '--token-parts=' + str( token_parts ), '--cq-level=' + str( cq_level ), '--kf-max-dist=' + str( kf_max_dist ), '--i420', '--fps=' + str( framerate[0] ) + '/' + str( framerate[1] ), '--width=' + str( dimensions[0] ), '--height=' + str( dimensions[1] ), '--ivf', '--output=' + os.devnull, '-' ], stdin=in_pipe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

def start_encode_vp8_video_pass_2( in_pipe, stats_path, out_path, dimensions, framerate, high_quality=False ):
	if high_quality:
		bitrate = 3200
		cq_level = 1
	else:
		bitrate = 1700
		cq_level = 4
	if dimensions[1] < 480:
		token_parts = 0
	elif dimensions[1] < 720:
		token_parts = 1
	elif dimensions[1] < 1080:
		token_parts = 2
	else:
		token_parts = 3
	kf_max_dist = math.floor( float( framerate[0] ) / float( framerate[1] ) * 10.0 )
	return subprocess.Popen( [ 'vpxenc', '--passes=2', '--pass=2', '--fpf=' + stats_path, '--threads=' + str( multiprocessing.cpu_count() ), '--best', '--lag-in-frames=16', '--end-usage=cq', '--target-bitrate=' + str( bitrate ), '--min-q=0', '--max-q=24', '--auto-alt-ref=1', '--token-parts=' + str( token_parts ), '--cq-level=' + str( cq_level ), '--kf-max-dist=' + str( kf_max_dist ), '--i420', '--fps=' + str( framerate[0] ) + '/' + str( framerate[1] ), '--width=' + str( dimensions[0] ), '--height=' + str( dimensions[1] ), '--ivf', '--output=' + out_path, '-' ], stdin=in_pipe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

def start_encode_vp8_video( in_path, out_path, dimensions, framerate ):
	if dimensions[1] < 480:
		token_parts = 0
	elif dimensions[1] < 720:
		token_parts = 1
	elif dimensions[1] < 1080:
		token_parts = 2
	else:
		token_parts = 3
	kf_max_dist = math.floor( float( framerate[0] ) / float( framerate[1] ) * 10.0 )
	return subprocess.Popen( [ 'vpxenc', '--passes=2', '--threads=' + str( multiprocessing.cpu_count() ), '--best', '--lag-in-frames=16', '--end-usage=cq', '--target-bitrate=1700', '--min-q=0', '--max-q=24', '--auto-alt-ref=1', '--token-parts=' + str( token_parts ), '--cq-level=4', '--kf-max-dist=' + str( kf_max_dist ), '--i420', '--fps=' + str( framerate[0] ) + '/' + str( framerate[1] ), '--width=' + str( dimensions[0] ), '--height=' + str( dimensions[1] ), '--ivf', '--output=' + out_path, in_path ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

def mux_matroska( path, video, audio, subtitles=None, attachments=None, chapters=None, title=None, video_lang=None, audio_lang=None, subtitles_lang=None, display_aspect=None, pixel_aspect=None, display_size=None ):
	command = [ 'mkvmerge' ]
	if title is not None:
		command.append( '--title' )
		command.append( title )
	if chapters is not None:
		command.append( '--chapters' )
		command.append( chapters )
	if attachments is not None:
		for i in sorted( glob.glob( os.path.join( attachments, '*' ) ) ):
			command.append( '--attach-file' )
			command.append( i )
	command.append( '--output' )
	command.append( path )
	if video_lang is not None:
		command.append( '--language' )
		command.append( '0:' + video_lang )
	if pixel_aspect is not None:
		command.append( '--aspect-ratio-factor' )
		command.append( '0:' + str( pixel_aspect[0] ) + '/' + str( pixel_aspect[1] ) )
	elif display_aspect is not None:
		command.append( '--aspect-ratio' )
		command.append( '0:' + str( display_aspect[0] ) + '/' + str( display_aspect[1] ) )
	elif display_size is not None:
		command.append( '--display-dimensions' )
		command.append( '0:' + str( display_size[0] ) + 'x' + str( display_size[1] ) )
	command.append( video )
	if audio_lang is not None:
		command.append( '--language' )
		command.append( '0:' + audio_lang )
	command.append( audio )
	if subtitles is not None:
		if subtitles_lang is not None:
			command.append( '--language' )
			command.append( '0:' + subtitles_lang )
		command.append( subtitles )
	subprocess.check_call( command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

def main( argv=None ):
	process_start_time = time.time()

	if argv is None:
		argv = sys.argv

	# Parse the command line
	command_line_parser = argparse.ArgumentParser( description='Convert videos to archive format.' )
	command_line_parser.add_argument( 'input', help='Input video file', metavar='FILE' )
	command_line_parser.add_argument( '-o', '--output', required=True, help='Path for output file', metavar='FILE' )
	command_line_parser.add_argument( '-I', '--info', action='store_true', help='Display input information' )
	command_line_parser.add_argument( '-H', '--high-quality', action='store_true', help='Use higher quality settings' )

	command_line_metadata_group = command_line_parser.add_argument_group( 'metadata' )
	command_line_metadata_group.add_argument( '-t', '--title', help='Specify a title for the video' )
	command_line_metadata_group.add_argument( '-V', '--video-language', help='Specify the language for the video', metavar='LANG' )
	command_line_metadata_group.add_argument( '-A', '--audio-language', help='Specify the language for the audio', metavar='LANG' )
	command_line_metadata_group.add_argument( '-S', '--subtitles-language', help='Specify the language for the subtitles', metavar='LANG' )

	command_line_disc_group = command_line_parser.add_argument_group( 'disc' )
	command_line_disc_group.add_argument( '-D', '--dvd', action='store_true', help='Indicate that the soure is a DVD' )
	command_line_disc_group.add_argument( '-B', '--bluray', action='store_true', help='Indicate that the soure is a Blu-ray' )
	command_line_disc_group.add_argument( '-T', '--disc-title', default=1, type=int, help='Specify disc title number', metavar='NUM' )
	command_line_disc_group.add_argument( '-Z', '--size', nargs=2, type=int, help='Specify input display dimensions (required for --bluray)', metavar=( 'W', 'H' ) )
	command_line_disc_group.add_argument( '-R', '--rate', nargs=2, type=int, help='Specify input frame rate (required for --bluray)', metavar=( 'N', 'D' ) )

	command_line_picture_group = command_line_parser.add_argument_group( 'picture' )
	command_line_picture_group.add_argument( '-d', '--deinterlace', action='store_true', help='Perform deinterlacing' )
	command_line_picture_group.add_argument( '-i', '--ivtc', action='store_true', help='Perform inverse telecine' )
	command_line_picture_group.add_argument( '-c', '--crop', nargs=4, type=int, help='Crop the picture', metavar=( 'W', 'H', 'X', 'Y' ) )
	command_line_picture_group.add_argument( '-s', '--scale', nargs=2, type=int, help='Scale the picture', metavar=( 'W', 'H' ) )
	command_line_picture_group.add_argument( '-a', '--display-aspect', nargs=2, type=int, help='Specify the display aspect of the picture', metavar=( 'W', 'H' ) )
	command_line_picture_group.add_argument( '-p', '--pixel-aspect', nargs=2, type=int, help='Specify the display pixel aspect of the picture', metavar=( 'W', 'H' ) )
	command_line_picture_group.add_argument( '-z', '--display-size', nargs=2, type=int, help='Specify the display dimensions of the picture', metavar=( 'W', 'H' ) )

	command_line_other_group = command_line_parser.add_argument_group( 'other' )
	command_line_other_group.add_argument( '--no-nice', action='store_true', help='Do not lower process priority' )
	command_line_other_group.add_argument( '--no-chapters', action='store_true', help='Do not include chapters from DVD/Matroska source' )
	command_line_other_group.add_argument( '--no-attachments', action='store_true', help='Do not include attachments from Matroska source' )

	command_line = command_line_parser.parse_args( argv[1:] )

	if command_line.bluray:
		if not command_line.size:
			print( 'Error: You must manually input the size of the input for Blu-ray sources!' )
			return 1
		if not command_line.rate:
			print( 'Error: You must manually input the frame rate of the input for Blu-ray sources!' )
			return 1

	if not command_line.no_nice:
		os.nice( 10 )

	print( 'Processing ' + os.path.basename( command_line.input ) + ' ...' )

	if command_line.dvd:
		disc_type = 'dvd'
	elif command_line.bluray:
		disc_type = 'bluray'
	else:
		disc_type = None

	avfile = AVFile( command_line.input, disc_type, command_line.disc_title, command_line.size, command_line.rate )

	if command_line.info:
		print( 'Printing probe data ...' )
		print( '\tContainer\t\t= ' + avfile.container_format )
		if avfile.has_subtitles:
			print( '\tSubtitles Type\t\t= ' + avfile.subtitles_type )
		else:
			print( '\tSubtitles Type\t\t= None' )
		print( '\tAttachment Count\t= ' + str( avfile.attachment_count ) )
		print( '\tVideo Format\t\t= ' + avfile.video_format )
		print( '\tVideo Dimensions\t= ' + str( avfile.video_dimensions[0] ) + 'x' + str( avfile.video_dimensions[1] ) )
		print( '\tVideo Frame Rate\t= ' + str( avfile.video_framerate_frac[0] ) + '/' + str( avfile.video_framerate_frac[1] ) + ' (' + str( round( avfile.video_framerate_float, 3 ) ) + ')' )
		print( '\tAudio Format\t\t= ' + avfile.audio_format )
		print( '\tAudio Channel Count\t= ' + str( avfile.audio_channelcnt ) )
		print( '\tAudio Sample Rate\t= ' + str( avfile.audio_samplerate ) )

	with tempfile.TemporaryDirectory( prefix='any2arch-' ) as work_dir:
		print( 'Created work directory: ' + work_dir + ' ...' )

		if avfile.has_chapters and not command_line.no_chapters:
			chapters_path = os.path.join( work_dir, 'chapters' )
			print( 'Extracting chapters ...' )
			avfile.extract_chapters( chapters_path )
		else:
			chapters_path = None

		if avfile.has_subtitles:
			subtitles_path = os.path.join( work_dir, 'subtitles' )
			print( 'Extracting ' + avfile.subtitles_type + ' subtitles ...' )
			avfile.extract_subtitles( subtitles_path )
		else:
			subtitles_path = None

		if avfile.attachment_count > 0 and not command_line.no_attachments:
			attachment_dir = os.path.join( work_dir, 'attachments' )
			print( 'Extracting attachments ...' )
			avfile.extract_attachments( attachment_dir )
		else:
			attachment_dir = None

		enc_audio_path = os.path.join( work_dir, 'audio.ogg' )
		if avfile.container_format == 'Matroska' and avfile.audio_format == 'Vorbis':
			print( 'Extracting Vorbis audio ...' )
			avfile.extract_audio( enc_audio_path )
		elif avfile.container_format == 'Matroska' and avfile.audio_format == 'FLAC':
			flac_audio_path = os.path.join( work_dir, 'audio.flac' )
			print( 'Extracting FLAC audio ...' )
			avfile.extract_audio( flac_audio_path )
			print( 'Encoding audio ...' )
			encode_vorbis_audio( flac_audio_path, enc_audio_path )
		elif avfile.container_format == 'Matroska' and avfile.audio_format == 'AAC':
			aac_audio_path = os.path.join( work_dir, 'audio.aac' )
			dec_audio_path = os.path.join( work_dir, 'audio.wav' )
			print( 'Extracting AAC audio ...' )
			avfile.extract_audio( aac_audio_path )
			print( 'Decoding AAC audio ...' )
			decode_aac_audio( aac_audio_path, dec_audio_path )
			print( 'Encoding audio ...' )
			encode_vorbis_audio( dec_audio_path, enc_audio_path )
		else:
			dec_audio_path = os.path.join( work_dir, 'audio.wav' )
			print( 'Decoding audio ...' )
			avfile.decode_audio( dec_audio_path )
			print( 'Encoding audio ...' )
			encode_vorbis_audio( dec_audio_path, enc_audio_path )

		enc_stats_path = os.path.join( work_dir, 'vpx_stats' )
		enc_video_path = os.path.join( work_dir, 'video.ivf' )

		if command_line.scale:
			out_video_dimensions = command_line.scale
		elif command_line.crop:
			out_video_dimensions = command_line.crop[0:2]
		else:
			out_video_dimensions = avfile.video_dimensions

		if command_line.ivtc:
			out_video_framerate = [ 24000, 1001 ]
		else:
			out_video_framerate = avfile.video_framerate_frac

		print( 'Encoding video (pass 1) ...' )
		dec_proc = avfile.start_decode_video( command_line.deinterlace, command_line.ivtc, command_line.crop, command_line.scale )
		enc_proc = start_encode_vp8_video_pass_1( dec_proc.stdout, enc_stats_path, out_video_dimensions, out_video_framerate, command_line.high_quality )
		dec_proc.stdout.close()
		if dec_proc.wait():
			print( 'Error: Error occurred in decoding process!' )
			return 1
		if enc_proc.wait():
			print( 'Error: Error occurred in encoding process!' )
			return 1

		print( 'Encoding video (pass 2) ...' )
		dec_proc = avfile.start_decode_video( command_line.deinterlace, command_line.ivtc, command_line.crop, command_line.scale )
		enc_proc = start_encode_vp8_video_pass_2( dec_proc.stdout, enc_stats_path, enc_video_path, out_video_dimensions, out_video_framerate, command_line.high_quality )
		dec_proc.stdout.close()
		if dec_proc.wait():
			print( 'Error: Error occurred in decoding process!' )
			return 1
		if enc_proc.wait():
			print( 'Error: Error occurred in encoding process!' )
			return 1

		print( 'Muxing ...' )
		mux_matroska( command_line.output, enc_video_path, enc_audio_path, subtitles_path, attachment_dir, chapters_path, command_line.title, command_line.video_language, command_line.audio_language, command_line.subtitles_language, command_line.display_aspect, command_line.pixel_aspect, command_line.display_size )

		print( 'Cleaning up ...' )

	if not command_line.bluray:
		print( 'File size ratio: ' + str( round( float( os.path.getsize( command_line.output ) ) / float( os.path.getsize( command_line.input ) ), 3 ) ) )
	print( 'Done. Process took ' + str( round( time.time() - process_start_time ) ) + ' seconds.' )
	return 0

if __name__ == '__main__':
	sys.exit( main() )
