import os
from os import path
import logging
import shutil
import csv
from copy import deepcopy as cpy
from threading import Thread
import time

from PyQt5 import QtCore
from PyQt5.QtWidgets import QFileDialog, QMainWindow, QApplication, QVBoxLayout
import appdirs
import numpy as np
from playsound import playsound

from ui_annotator import Ui_MainWindow  # Annotator's generated ui file
from new_session import NewSession
from ui_alert import AlertOk, AlertYayNay
import session
from goto import GoTo



class Annotator(QMainWindow):

    # signals (must be defined here)
    saved_audio_file = QtCore.pyqtSignal()
    now_show_info = QtCore.pyqtSignal()

    def __init__(self):
        QMainWindow.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)

        # set up UI
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # connect signals (all used to make threads & updates possible)
        self.ui.viewer.show_new_file_info.connect(self.show_new_file_info)
        self.ui.table.show_msg.connect(self.show_timed_msg)
        self.saved_audio_file.connect(self.save_to_csv)
        self.now_show_info.connect(self.show_file_info)

        # connect new and load 
        self.ui.actionNew.triggered.connect(self.new_session)
        self.ui.actionLoad.triggered.connect(self.load_session)
        self.ui.actionExit.triggered.connect(self.quit_session)

        # class vars updated in load clips
        self.d_fp = None
        self.s_fp = None
        self.csv_fn = None
        self.ss_fp = None
        self.min_dur = None
        self.f_ind = None
        self.m_ind = None
        self.wav_files = None

    def load_clips(self, d_fp, s_fp, csv_fn, ss_fp, min_dur, f_ind=0, m_ind=0):
        self.status(self.logger, 'setting up session...')
        self.d_fp = d_fp
        self.s_fp = s_fp
        self.csv_fn = csv_fn
        self.ss_fp = ss_fp
        self.min_dur = min_dur
        self.f_ind = f_ind
        self.m_ind = m_ind

        # get all wav files contained in given directory or subdirectories
        self.wav_files = []
        for rootdir, dirs, filenames in os.walk(self.d_fp):
            for filename in filenames:
                if 'wav' in filename or 'WAV' in filename:
                    self.wav_files.append(filename)
            break  # activate this line if only top level of directory wanted

        if not self.wav_files:
            self.status(self.logger, 'No wav files found in {}'.format(self.d_fp))
        else:
            # set up the csv table
            self.ui.table.load_table(path.join(self.s_fp, self.csv_fn))

            # enable buttons and connect to slots
            self.ui.playButton.setEnabled(True)
            self.ui.saveButton.setEnabled(True)
            self.ui.nextButton.setEnabled(True)
            self.ui.prevButton.setEnabled(True)
            self.ui.playButton.clicked.connect(self.play)
            self.ui.saveButton.clicked.connect(self.check_tag)
            self.ui.nextButton.clicked.connect(self.next_)
            self.ui.prevButton.clicked.connect(self.prev)

            # enable menu actions and connect to slots
            self.ui.actionPlay.setEnabled(True)
            self.ui.actionSave.setEnabled(True)
            self.ui.actionNext.setEnabled(True)
            self.ui.actionPrev.setEnabled(True)
            self.ui.actionGoto.setEnabled(True)
            self.ui.actionPlay.triggered.connect(self.play)
            self.ui.actionSave.triggered.connect(self.check_tag)
            self.ui.actionNext.triggered.connect(self.next_)
            self.ui.actionPrev.triggered.connect(self.prev)
            self.ui.actionGoto.triggered.connect(self.goto)

            # this is so the spectrum viewer works properly
            lay = QVBoxLayout(self.ui.scrollAreaWidgetContents)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.ui.viewer)
            self.ui.scrollArea.setWidgetResizable(True)

            # start by loading the first clip
            self.ui.viewer.new_clip(path.join(self.d_fp, self.curr_filename()))

    def curr_filename(self):
        return self.wav_files[self.f_ind]

    def curr_save_filename(self):
        return 'v{}-{}.wav'.format(self.curr_filename().split('.')[0], self.m_ind)

    def curr_display_msg(self):
        return 'displaying clip #{} ({}) recorded at {} {} on {}'.format(
            self.f_ind, 
            self.curr_filename(), 
            self.ui.viewer.curr_clip.metadata['time'], 
            self.ui.viewer.curr_clip.metadata['timezone'], 
            self.ui.viewer.curr_clip.metadata['date']
            )

    def new_session(self):
        self.status(self.logger, 'loading new session...')
        NewSession(self).show()

    def load_session(self):
        self.status(self.logger, 'loading existing session...')
        ss_fp, _ = QFileDialog.getOpenFileName(self, filter='(*.yaml)')

        try:
            d_fp, s_fp, csv_fn, min_dur, f_ind, m_ind = session.load(ss_fp)
            self.load_clips(d_fp, s_fp, csv_fn, ss_fp, float(min_dur), int(f_ind), int(m_ind))

        except FileNotFoundError:
            self.status(self.logger, 'unable to find: \'{}\''.format(ss_fp))

    def quit_session(self):
        self.status(self.logger, 'quitting session...')

        msg = 'Would you like to save your current session as a .yaml file?'

        def yes_fun():
            path, _ = QFileDialog.getSaveFileName(self, filter='(*.yaml)')

            try:
                session.save(path, self.d_fp, self.s_fp, self.csv_fn, 
                    str(self.min_dur), str(self.f_ind), str(self.m_ind)
                )
                self.exit()
                
            except FileNotFoundError:
                self.annotator.status('unable to find: \'{}\''.format(path))
                self.open()

        AlertYayNay(self, msg, yes_fun, lambda _: self.exit()).show()

    def exit(self):
        self.status(self.logger, 'exiting main application...')
        QApplication.quit()

    def play(self):
        self.status(self.logger, 'playing selection...')

        def thread_play():
            playsound('./temp.wav')
            self.now_show_info.emit()

        Thread(target=thread_play).start()

    def check_tag(self):
        tag = self.ui.tag.text()

        if tag == '':
            msg = 'This audio selection has no label. Proceed?'
            def yes_fun():
                self.save_audio_file()
                alert.done(os.EX_OK)
            def no_fun():
                self.status(self.logger, 'save selection canceled')
                def delay():
                    time.sleep(1)
                    self.now_show_info.emit() 
                Thread(target=delay).start() 
                alert.done(os.EX_OK)
            alert = AlertYayNay(self, msg, yes_fun , no_fun)
            alert.show()
        else:
            self.save_audio_file()

    def save_audio_file(self):
        savepath = path.join(self.s_fp, self.curr_save_filename())
        self.status(self.logger, 'saving selection to {}...'.format(savepath))

        def thread_save():
            try:
                shutil.copy('./temp.wav', savepath)
                self.saved_audio_file.emit()
                
            except IOError as err:
                self.logger.error(err)
                self.ui.statusbar.showMessage('Error: unable to save file!')

        Thread(target=thread_save).start()

    def save_to_csv(self):
        savepath = path.join(self.s_fp, self.curr_save_filename())
        self.ui.table.add_row([savepath, self.ui.tag.text()])
        self.m_ind += 1
        savepath = path.join(self.s_fp, self.curr_save_filename())
        msg = 'saved new audio file as {}'.format(savepath)
        self.show_timed_msg(self.logger, msg) 

    def next_(self):
        self.status(self.logger, 'getting next clip...')
        self.f_ind += 1
        if self.f_ind >= len(self.wav_files):
            msg = 'There are no more wav files.\nYou are done!'
            AlertOk(self, msg, lambda _: self.exit()).show()
        else:
            # figure out what next m_ind should be  TODO: maybe look in csv instead?
            highest = -1
            for filename in os.listdir(self.s_fp):
                if self.curr_filename().split('.')[0] in filename:  # if voc pertains to current file
                    ind = int(filename.split('-')[-1].split('.')[0])
                    if ind > highest:
                        highest = cpy(ind)

            self.m_ind = highest + 1

            Thread(target=self.ui.viewer.new_clip, args=[path.join(self.d_fp, self.curr_filename())]).start()

    def prev(self):
        self.status(self.logger, 'getting previous clip...')
        self.f_ind -= 1
        if self.f_ind < 0:
            msg = 'This is the first file.'
            alert = AlertOk(self, msg, lambda _: alert.done(os.EX_OK))
            alert.show()
        else:
            # figure out what next m_ind should be
            highest = -1
            for filename in os.listdir(self.s_fp):
                if self.curr_filename().split('.')[0] in filename:  # if voc pertains to current file
                    ind = int(filename.split('-')[-1].split('.')[0])
                    if ind > highest:
                        highest = cpy(ind)

            self.m_ind = highest + 1

            Thread(target=self.ui.viewer.new_clip, args=[path.join(self.d_fp, self.curr_filename())]).start()

    def goto(self):
        self.status(self.logger, 'going to...')
        GoTo(self).show()

    def show_timed_msg(self, logger, msg):
        self.status(logger, msg)
        def delay():
            time.sleep(1.5)
            self.now_show_info.emit() 
        Thread(target=delay).start()  

    def show_file_info(self):
        self.ui.statusbar.showMessage(self.curr_display_msg())

    def show_new_file_info(self, logger):
        logger.info(self.curr_display_msg())
        self.ui.statusbar.showMessage(self.curr_display_msg())

    def status(self, logger, msg):
        logger.info(msg)
        self.ui.statusbar.showMessage(msg)
