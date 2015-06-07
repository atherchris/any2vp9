#!/usr/bin/env python3

#
# Copyright (c) 2015 Christopher Atherton <the8lack8ox@gmail.com>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#    Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
#    Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

import glob
import math
import os
import re
import sys
import time

import argparse
import datetime
import fractions
import tempfile
import subprocess

PROGRAM_NAME = 'any2vp9'

class AVExtractor:
	CHAPTERS_TIME_RE = re.compile( r'^CHAPTER(\d+)=(\d\d):(\d\d):(\d\d)\.(\d\d\d)$' )
	CHAPTERS_TITLE_1_RE = re.compile( r'^CHAPTER(\d+)NAME=Chapter (\d+)$' )
	CHAPTERS_TITLE_2_RE = re.compile( r'^CHAPTER(\d+)NAME=(.*)$' )

	def __init__( self, path, disc_type=None, disc_title=1, chap_start=None, chap_end=None, maid=None, msid=None ):
		self.path = os.path.abspath( path )
		self.disc_type = disc_type

		self.__mplayer_input_args = ( )

		if maid is not None:
			self.__mplayer_input_args += ( '-aid', str( maid ) )
		if msid is not None:
			self.__mplayer_input_args += ( '-sid', str( msid ) )

		if disc_type == 'dvd':
			self.disc_title = disc_title
			self.__mplayer_input_args += ( '-dvd-device', path, 'dvd://' + str( disc_title ) )
		elif disc_type == 'bluray':
			self.disc_title = disc_title
			self.__mplayer_input_args += ( '-bluray-device', path, 'bluray://' + str( disc_title ) )
		else:
			self.__mplayer_input_args += ( path, )

		mplayer_probe_out = subprocess.check_output( ( 'mplayer', '-nocorrect-pts', '-vo', 'null', '-ac', 'ffmp3,', '-ao', 'null', '-endpos', '1' ) + self.__mplayer_input_args, stderr=subprocess.STDOUT ).decode()

		if disc_type != 'bluray':
			mat = re.search( r'^VIDEO:  \[?(\w+)\]?  (\d+)x(\d+) .+ (\d+\.\d+) fps', mplayer_probe_out, re.M )
			self.video_codec = mat.group( 1 )
			self.video_dimensions = ( int( mat.group( 2 ) ), int( mat.group( 3 ) ) )

			self.video_framerate = float( mat.group( 4 ) )
			if abs( math.ceil( self.video_framerate ) / 1.001 - self.video_framerate ) / self.video_framerate < 0.00001:
				self.video_framerate_frac = ( math.ceil( self.video_framerate ) * 1000, 1001 )
				self.video_framerate = float( self.video_framerate_frac[0] ) / float( self.video_framerate_frac[1] )
			else:
				self.video_framerate_frac = fractions.Fraction( self.video_framerate )
				self.video_framerate_frac = ( self.video_framerate_frac.numerator, self.video_framerate_frac.denominator )

		mat = re.search( r'^AUDIO: (\d+) Hz, (\d+) ch', mplayer_probe_out, re.M )
		self.audio_samplerate = int( mat.group( 1 ) )
		self.audio_channels = int( mat.group( 2 ) )

		mat = re.search( r'^Selected audio codec: \[(\w+)\]', mplayer_probe_out, re.M )
		self.audio_codec = mat.group( 1 )

		self.chap_start = chap_start
		self.chap_end = chap_end
		if chap_start is not None:
			chap_arg = str( chap_start )
			if chap_end is not None:
				chap_arg += '-' + str( chap_end )
			self.__mplayer_input_args += ( '-chapter', chap_arg )
		elif chap_end is not None:
			self.__mplayer_input_args += ( '-chapter', '-' + str( chap_end ) )

		self.is_matroska = os.path.splitext( path )[1].upper() == '.MKV'
		if disc_type == 'dvd':
			# Chapters
			self.has_chapters = True

			# Attachments
			self.attachment_cnt = 0

			# Subtitles
			if re.search( r'^number of subtitles on disk: [1-9]', mplayer_probe_out, re.M ) is not None:
				self.has_subtitles = True
			else:
				self.has_subtitles = False
		elif self.is_matroska:
			mkvmerge_probe_out = subprocess.check_output( ( 'mkvmerge', '--identify', path ), stderr=subprocess.DEVNULL ).decode()

			# Chapters
			self.has_chapters = 'Chapters: ' in mkvmerge_probe_out

			# Attachments
			self.attachment_cnt = mkvmerge_probe_out.count( 'Attachment ID ' )

			# Subtitles
			mat = re.search( r'^Track ID (\d+): subtitles', mkvmerge_probe_out, re.M )
			if mat is not None:
				self.has_subtitles = True
				self.__mkv_subtitle_tracknum = int( mat.group( 1 ) )
			else:
				self.has_subtitles = False
		else:
			self.has_chapters = False
			self.attachment_cnt = 0
			self.has_subtitles = False

	def extract_chapters( self, filename ):
		if self.is_matroska:
			chapters = subprocess.check_output( ( 'mkvextract', 'chapters', self.path, '--simple' ), stderr=subprocess.DEVNULL ).decode()
		elif self.disc_type == 'dvd':
			chapters = subprocess.check_output( ( 'dvdxchap', '--title', str( self.disc_title ), self.path ), stderr=subprocess.DEVNULL ).decode()
		else:
			raise Exception( 'Cannot extract chapters because there are none.' )

		new_chapters = str()
		if self.chap_start is not None or self.chap_end is not None:
			if self.chap_start is not None:
				offset_index = self.chap_start - 1
				mat = re.search( r'^CHAPTER' + str( self.chap_start ).zfill( 2 ) + r'=(\d\d):(\d\d):(\d\d)\.(\d\d\d)$', chapters, re.M )
				if mat is None:
					raise Exception( 'Start chapter could not be found!' )
				offset_time = datetime.timedelta( hours=int( mat.group( 1 ) ), minutes=int( mat.group( 2 ) ), seconds=int( mat.group( 3 ) ), milliseconds=int( mat.group( 4 ) ) )
			else:
				offset_index = 0
				offset_time = datetime.timedelta()
		else:
			offset_index = 0
			offset_time = datetime.timedelta()
		for line in chapters.splitlines():
			mat = self.CHAPTERS_TIME_RE.match( line )
			if mat is not None and ( self.chap_start is None or int( mat.group( 1 ) ) >= self.chap_start ) and ( self.chap_end is None or int( mat.group( 1 ) ) <= self.chap_end ):
				new_time = datetime.timedelta( hours=int( mat.group( 2 ) ), minutes=int( mat.group( 3 ) ), seconds=int( mat.group( 4 ) ), milliseconds=int( mat.group( 5 ) ) ) - offset_time
				new_chapters += 'CHAPTER' + str( int( mat.group( 1 ) ) - offset_index ).zfill( 2 ) + '=' + str( new_time.seconds // 3600 ).zfill( 2 ) + ':' + str( new_time.seconds // 60 % 60 ).zfill( 2 ) + ':' + str( new_time.seconds % 60 ).zfill( 2 ) + '.' + str( new_time.microseconds // 1000 ).zfill( 3 ) + '\n'
			else:
				mat = self.CHAPTERS_TITLE_1_RE.match( line )
				if mat is not None and ( self.chap_start is None or int( mat.group( 1 ) ) >= self.chap_start ) and ( self.chap_end is None or int( mat.group( 1 ) ) <= self.chap_end ):
					new_chapters += 'CHAPTER' + str( int( mat.group( 1 ) ) - offset_index ).zfill( 2 ) + 'NAME=Chapter ' + str( int( mat.group( 2 ) ) - offset_index ).zfill( 2 ) + '\n'
				else:
					mat = self.CHAPTERS_TITLE_2_RE.match( line )
					if mat is not None and ( self.chap_start is None or int( mat.group( 1 ) ) >= self.chap_start ) and ( self.chap_end is None or int( mat.group( 1 ) ) <= self.chap_end ):
						new_chapters += 'CHAPTER' + str( int( mat.group( 1 ) ) - offset_index ).zfill( 2 ) + 'NAME=' + mat.group( 2 ) + '\n'

		with open( filename, 'w' ) as f:
			f.write( new_chapters )

	def extract_attachments( self, directory ):
		os.mkdir( directory )
		cwd = os.getcwd()
		os.chdir( directory )
		subprocess.check_call( ( 'mkvextract', 'attachments', self.path ) + tuple( map( str, range( 1, self.attachment_cnt + 1 ) ) ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
		os.chdir( cwd )

	def extract_subtitles( self, filename ):
		if self.has_subtitles and self.is_matroska:
			subprocess.check_call( ( 'mkvextract', 'tracks', self.path, str( self.__mkv_subtitle_tracknum ) + ':' + filename ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
		elif self.has_subtitles and self.disc_type == 'dvd':
			subprocess.check_call( ( 'mencoder', '-ovc', 'copy', '-o', os.devnull, '-vobsubout', filename ) + self.__mplayer_input_args + ( '-nosound', ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
		else:
			raise Exception( 'Cannot extract subtitles (no subtitles)!' )

	def extract_audio( self, filename ):
		if self.is_matroska and self.chap_start is None and self.chap_end is None and self.audio_codec == 'ffvorbis':
			# Matroska with Vorbis audio
			subprocess.check_call( ( 'mkvextract', 'tracks', self.path, re.search( r'^Track ID (\d+): audio \((.+)\)', self.__mkvmerge_probe_out, re.M ).group( 1 ) + ':' + filename ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
		else:
			raise Exception( 'Cannot extract audio (audio is not Vorbis).' )

	def decode_audio( self ):
		if self.is_matroska and self.chap_start is None and self.chap_end is None and self.audio_codec == 'ffflac':
			# Matroska with FLAC audio
			return subprocess.Popen( ( 'mkvextract', '--redirect-output', '/dev/stderr', 'tracks', self.path, re.search( r'^Track ID (\d+): audio \((.+)\)', self.__mkvmerge_probe_out, re.M ).group( 1 ) + ':/dev/stdout' ), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL )
		else:
			return subprocess.Popen( ( 'mplayer', '-quiet', '-really-quiet', '-nocorrect-pts', '-vc', 'null', '-vo', 'null', '-channels', str( self.audio_channels ), '-ao', 'pcm:fast:file=/dev/stdout' ) + self.__mplayer_input_args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL )

	def decode_video( self, pp=False, scale=None, crop=None, deint=False, ivtc=False, force_rate=None ):
		filters = 'format=i420,'
		if ivtc:
			if crop is None:
				filters += 'filmdint=fast=0,'
			else:
				filters += 'filmdint=fast=0/crop=' + ':'.join( map( str, crop ) ) + ','
			ofps = ( '-ofps', '24000/1001' )
		elif force_rate is not None:
			ofps = ( '-ofps', '/'.join( map( str, force_rate ) ) )
		else:
			ofps = tuple()
		if deint:
			filters += 'yadif=1,'
		if crop is not None and not ivtc:
			filters += 'crop=' + ':'.join( map( str, crop ) ) + ','
		if scale is not None:
			filters += 'scale=' + ':'.join( map( str, scale ) ) + ','
		if pp:
			filters += 'pp=ha/va/dr,'
		filters += 'hqdn3d,harddup'

		return subprocess.Popen( ( 'mencoder', '-quiet', '-really-quiet', '-sws', '9', '-vf', filters ) + ofps + ( '-ovc', 'raw', '-of', 'rawvideo', '-o', '-' ) + self.__mplayer_input_args + ( '-nosound', '-nosub' ), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL )

def encode_vorbis_audio( extract_proc, out_file ):
	enc_proc = subprocess.Popen( ( 'oggenc', '--ignorelength', '--discard-comments', '-o', out_file, '-' ), stdin=extract_proc.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
	extract_proc.stdout.close()
	if extract_proc.wait():
		raise Exception( 'Error occurred in decoding process!' )
	if enc_proc.wait():
		raise Exception( 'Error occurred in encoding process!' )

def encode_vp9_video_pass1( extract_proc, vpx_stats, dimensions, framerate ):
	bitrate = round( ( 3000 - 1000 ) / ( 1080 - 480 ) * dimensions[1] - 600 )
	kf_max_dist = math.floor( float( framerate[0] ) / float( framerate[1] ) * 10.0 )
	enc_proc = subprocess.Popen( ( 'vpxenc', '--output=' + os.devnull, '--codec=vp9', '--passes=2', '--pass=1', '--fpf=' + vpx_stats, '--best', '--ivf', '--i420', '--width=' + str( dimensions[0] ), '--height=' + str( dimensions[1] ), '--fps=' + str( framerate[0] ) + '/' + str( framerate[1] ), '--lag-in-frames=16', '--end-usage=cq', '--target-bitrate=' + str( bitrate ), '--min-q=0', '--max-q=48', '--kf-max-dist=' + str( kf_max_dist ), '--auto-alt-ref=1', '--cq-level=16', '--frame-parallel=1', '-' ), stdin=extract_proc.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
	extract_proc.stdout.close()
	if extract_proc.wait():
		raise Exception( 'Error occurred in decoding process!' )
	if enc_proc.wait():
		raise Exception( 'Error occurred in encoding process!' )

def encode_vp9_video_pass2( extract_proc, out_file, vpx_stats, dimensions, framerate ):
	bitrate = round( ( 3000 - 1000 ) / ( 1080 - 480 ) * dimensions[1] - 600 )
	kf_max_dist = math.floor( float( framerate[0] ) / float( framerate[1] ) * 10.0 )
	enc_proc = subprocess.Popen( ( 'vpxenc', '--output=' + out_file, '--codec=vp9', '--passes=2', '--pass=2', '--fpf=' + vpx_stats, '--best', '--ivf', '--i420', '--width=' + str( dimensions[0] ), '--height=' + str( dimensions[1] ), '--fps=' + str( framerate[0] ) + '/' + str( framerate[1] ), '--lag-in-frames=16', '--end-usage=cq', '--target-bitrate=' + str( bitrate ), '--min-q=0', '--max-q=48', '--kf-max-dist=' + str( kf_max_dist ), '--auto-alt-ref=1', '--cq-level=16', '--frame-parallel=1', '-' ), stdin=extract_proc.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
	extract_proc.stdout.close()
	if extract_proc.wait():
		raise Exception( 'Error occurred in decoding process!' )
	if enc_proc.wait():
		raise Exception( 'Error occurred in encoding process!' )

def mux_matroska_mkv( out_file, title, chapters, attachments, vid_file, vid_lang, vid_aspect, vid_pixaspect, vid_displaysize, aud_file, aud_lang, sub_file, sub_lang ):
	cmd = ( 'mkvmerge', )
	if title is not None:
		cmd += ( '--title', title )
	if chapters is not None:
		cmd += ( '--chapters', chapters )
	if attachments is not None:
		for i in sorted( glob.glob( os.path.join( attachments, '*' ) ) ):
			cmd += ( '--attach-file', i )
	cmd += ( '--output', out_file )
	if vid_lang is not None:
		cmd += ( '--language', '0:' + vid_lang )
	if vid_aspect is not None:
		cmd += ( '--aspect-ratio', '0:' + str( vid_aspect[0] ) + '/' + str( vid_aspect[1] ) )
	if vid_pixaspect is not None:
		cmd += ( '--aspect-ratio-factor', '0:' + str( vid_pixaspect[0] ) + '/' + str( vid_pixaspect[1] ) )
	if vid_displaysize is not None:
		cmd += ( '--display-dimensions', '0:' + str( vid_displaysize[0] ) + 'x' + str( vid_displaysize[1] ) )
	cmd += ( vid_file, )
	if aud_lang is not None:
		cmd += ( '--language', '0:' + aud_lang )
	cmd += ( aud_file, )
	if sub_lang is not None:
		cmd += ( '--language', '0:' + sub_lang )
	if sub_file is not None:
		cmd += ( sub_file, )
	subprocess.check_call( cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )

def main( argv=None ):
	process_start_time = time.time()

	# Parse command line
	command_line_parser = argparse.ArgumentParser( description='convert videos to VP9 format' )
	command_line_parser.add_argument( 'input', help='input video file', metavar='FILE' )
	command_line_parser.add_argument( '-o', '--output', required=True, help='path for output file', metavar='FILE' )

	command_line_track_group = command_line_parser.add_argument_group( 'track' )
	command_line_track_group.add_argument( '-u', '--mplayer-aid', type=int, help='set audio track (in MPlayer aid)', metavar='INT' )
	command_line_track_group.add_argument( '-v', '--mplayer-sid', type=int, help='set subtitle track (in MPlayer sid)', metavar='INT' )

	command_line_disc_group = command_line_parser.add_argument_group( 'disc' )
	command_line_disc_mutex_group = command_line_disc_group.add_mutually_exclusive_group()
	command_line_disc_mutex_group.add_argument( '-D', '--dvd', action='store_true', help='indicate that the soure is a DVD' )
	command_line_disc_mutex_group.add_argument( '-B', '--bluray', action='store_true', help='indicate that the soure is a Blu-ray' )
	command_line_disc_group.add_argument( '-T', '--disc-title', default=1, type=int, help='set disc title number (default: 1)', metavar='INT' )
	command_line_disc_group.add_argument( '-Z', '--size', nargs=2, type=int, help='force input display dimensions (required for --bluray)', metavar=( 'W', 'H' ) )
	command_line_disc_group.add_argument( '-R', '--rate', nargs=2, type=int, help='force input frame rate (required for --bluray and progressive --dvd)', metavar=( 'N', 'D' ) )

	command_line_chapter_group = command_line_parser.add_argument_group( 'chapters' )
	command_line_chapter_group.add_argument( '-C', '--start-chapter', type=int, help='start at certain chapter', metavar='INT' )
	command_line_chapter_group.add_argument( '-E', '--end-chapter', type=int, help='stop at certain chapter', metavar='INT' )

	command_line_metadata_group = command_line_parser.add_argument_group( 'metadata' )
	command_line_metadata_group.add_argument( '-t', '--title', help='set video title', metavar='STRING' )
	command_line_metadata_group.add_argument( '-V', '--video-language', help='set video language', metavar='LANG' )
	command_line_metadata_group.add_argument( '-A', '--audio-language', help='set audio language', metavar='LANG' )
	command_line_metadata_group.add_argument( '-S', '--subtitles-language', help='set subtitle language', metavar='LANG' )

	command_line_picture_group = command_line_parser.add_argument_group( 'picture' )
	command_line_picture_group.add_argument( '-p', '--post-process', action='store_true', help='perform post-processing' )
	command_line_picture_group.add_argument( '-d', '--deinterlace', action='store_true', help='perform deinterlacing' )
	command_line_picture_group.add_argument( '-i', '--ivtc', action='store_true', help='perform inverse telecine' )
	command_line_picture_group.add_argument( '-c', '--crop', nargs=4, type=int, help='crop the picture', metavar=( 'W', 'H', 'X', 'Y' ) )
	command_line_picture_group.add_argument( '-s', '--scale', nargs=2, type=int, help='scale the picture', metavar=( 'W', 'H' ) )
	command_line_picture_aspect_group = command_line_picture_group.add_mutually_exclusive_group()
	command_line_picture_aspect_group.add_argument( '-a', '--display-aspect', nargs=2, type=int, help='set the display aspect of the picture', metavar=( 'W', 'H' ) )
	command_line_picture_aspect_group.add_argument( '-x', '--pixel-aspect', nargs=2, type=int, help='set the display pixel aspect of the picture', metavar=( 'W', 'H' ) )
	command_line_picture_aspect_group.add_argument( '-z', '--display-size', nargs=2, type=int, help='set the display dimensions of the picture', metavar=( 'W', 'H' ) )

	command_line_other_group = command_line_parser.add_argument_group( 'other' )
	command_line_other_group.add_argument( '--no-nice', action='store_true', help='do not lower process priority' )
	command_line_other_group.add_argument( '--no-chapters', action='store_true', help='do not include chapters from DVD/Matroska source' )
	command_line_other_group.add_argument( '-N', '--no-subtitles', action='store_true', help='do not include subtitles from DVD/Matroska source' )
	command_line_other_group.add_argument( '--no-attachments', action='store_true', help='do not include attachments from Matroska source' )

	if argv is None:
		command_line = command_line_parser.parse_args()
	else:
		command_line = command_line_parser.parse_args( argv )

	# Verify command line sanity
	if command_line.bluray:
		if command_line.size is None:
			print( 'ERROR: You must manually input the size of the input for Blu-ray sources!' )
			return 1
		if command_line.rate is None:
			print( 'ERROR: You must manually input the frame rate of the input for Blu-ray sources!' )
			return 1

	# Reduce priority
	if not command_line.no_nice:
		os.nice( 10 )

	# Process
	print( 'Processing', os.path.basename( command_line.input ), '...' )

	if command_line.dvd:
		disc_type = 'dvd'
	elif command_line.bluray:
		disc_type = 'bluray'
	else:
		disc_type = None

	extractor = AVExtractor( command_line.input, disc_type, command_line.disc_title, command_line.start_chapter, command_line.end_chapter, command_line.mplayer_aid, command_line.mplayer_sid )

	with tempfile.TemporaryDirectory( prefix=PROGRAM_NAME+'-' ) as work_dir:
		print( 'Created work directory:', work_dir, '...' )

		# Chapters
		if extractor.has_chapters and not command_line.no_chapters:
			print( 'Extracting chapters ...', end=str(), flush=True )
			chapters_path = os.path.join( work_dir, 'chapters' )
			extractor.extract_chapters( chapters_path )
			print( ' done.', flush=True )
		else:
			chapters_path = None

		# Attachments
		if extractor.attachment_cnt > 0 and not command_line.no_attachments:
			print( 'Extracting ' + str( extractor.attachments_cnt ) + ' attachment(s) ...', end=str(), flush=True )
			attachments_path = os.path.join( work_dir, 'attachments' )
			extractor.extract_attachments( attachments_path )
			print( ' done.', flush=True )
		else:
			attachments_path = None

		# Subtitles
		if extractor.has_subtitles and not command_line.no_subtitles:
			print( 'Extracting subtitles ...', end=str(), flush=True )
			subtitles_path = os.path.join( work_dir, 'subtitles' )
			extractor.extract_subtitles( subtitles_path )
			if command_line.dvd:
				subtitles_path += '.idx'
			print( ' done.', flush=True )
		else:
			subtitles_path = None

		# Audio
		audio_path = os.path.join( work_dir, 'audio.ogg' )
		if extractor.is_matroska and extractor.chap_start is None and extractor.chap_end is None and extractor.audio_codec == 'ffvorbis':
			print( 'Extracting audio ...', end=str(), flush=True )
			extractor.extract_audio( audio_path )
			print( ' done.', flush=True )
		else:
			print( 'Transcoding audio ...', end=str(), flush=True )
			encode_vorbis_audio( extractor.decode_audio(), audio_path )
			print( ' done.', flush=True )

		# Final dimension and frame rate calculations
		if command_line.scale is not None:
			final_dimensions = command_line.scale
		elif command_line.crop is not None:
			final_dimensions = command_line.crop[0:2]
		elif command_line.size is not None:
			final_dimensions = command_line.size
		else:
			final_dimensions = extractor.video_dimensions
		if command_line.ivtc:
			final_rate = ( 24000, 1001 )
		elif command_line.rate is not None:
			final_rate = tuple( command_line.rate )
		else:
			final_rate = extractor.video_framerate_frac
		if command_line.deinterlace:
			final_rate = ( 2*final_rate[0], final_rate[1] )
		final_rate_frac = fractions.Fraction( final_rate[0], final_rate[1] )
		final_rate = ( final_rate_frac.numerator, final_rate_frac.denominator )

		# Transcode video
		vpx_stats_path = os.path.join( work_dir, 'vpx_stats' )
		video_path = os.path.join( work_dir, 'video.ivf' )
		print( 'Transcoding video (pass 1) ...', end=str(), flush=True )
		encode_vp9_video_pass1( extractor.decode_video( command_line.dvd or command_line.post_process, command_line.scale, command_line.crop, command_line.deinterlace, command_line.ivtc, command_line.rate ), vpx_stats_path, final_dimensions, final_rate )
		print( ' done.', flush=True )
		print( 'Transcoding video (pass 2) ...', end=str(), flush=True )
		encode_vp9_video_pass2( extractor.decode_video( command_line.dvd or command_line.post_process, command_line.scale, command_line.crop, command_line.deinterlace, command_line.ivtc, command_line.rate ), video_path, vpx_stats_path, final_dimensions, final_rate )
		print( ' done.', flush=True )

		# Mux
		print( 'Multiplexing ...', end=str(), flush=True )
		mux_matroska_mkv( command_line.output, command_line.title, chapters_path, attachments_path, video_path, command_line.video_language, command_line.display_aspect, command_line.pixel_aspect, command_line.display_size, audio_path, command_line.audio_language, subtitles_path, command_line.subtitles_language )
		print( ' done.', flush=True )

	# Done
	process_time = round( time.time() - process_start_time )
	print( 'Finished. Process took', process_time // 3600, 'hours,', process_time // 60 % 60, 'minutes, and', process_time % 60, 'seconds.', file=sys.stderr )
	return 0

if __name__ == '__main__':
	sys.exit( main() )
