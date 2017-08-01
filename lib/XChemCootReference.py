# last edited: 28/07/2017 - 15:00

import sys,glob
import os
import pickle
import time
import gtk
import threading
import gobject
gtk.gdk.threads_init()

from matplotlib.figure import Figure
from matplotlib.backends.backend_gtkagg import FigureCanvasGTKAgg as FigureCanvas

# XCE libraries
sys.path.append(os.getenv('XChemExplorer_DIR')+'/lib')
import XChemRefine
import XChemUtils
import XChemLog

# libraries from COOT
#import pygtk, gtk, pango
import coot

# had to adapt the original coot_utils.py file
# otherwise unable to import the original file without complaints about missing modules etc.
# modified file is now in $XChemExplorer_DIR/lib
import coot_utils_XChem


class GUI(object):

    """
    main class which opens the actual GUI
    """

    def __init__(self):

        ###########################################################################################
        # read in settings file from XChemExplorer to set the relevant paths
        self.settings = pickle.load(open(".xce_settings.pkl","rb"))
        remote_qsub_submission=self.settings['remote_qsub']
        self.database_directory=self.settings['database_directory']
        self.xce_logfile=self.settings['xce_logfile']
        self.Logfile=XChemLog.updateLog(self.xce_logfile)
        self.Logfile.insert('starting COOT gui for reference model refinement')
        self.data_source=self.settings['data_source']

        # checking for external software packages
        self.external_software=XChemUtils.external_software(self.xce_logfile).check()
        self.external_software['qsub_remote']=remote_qsub_submission

        # the Folder is kind of a legacy thing because my inital idea was to have separate folders
        # for Data Processing and Refinement
        self.reference_directory = self.settings['reference_directory']
        self.refinementDir = ''
        self.Serial=0
        self.Refine=None

        self.xtalID=''
        self.compoundID=''
        self.spider_plot=''
        self.refinement_folder=''
        self.pdbFile=''

        self.pdb_style='refine.pdb'
        self.mtz_style='refine.mtz'

        # stores imol of currently loaded molecules and maps
        self.mol_dict = {   'protein':  -1,
                            'ligand':   -1,
                            '2fofc':    -1,
                            'fofc':     -1,
                            'event':    -1  }

        self.job_running=False

        ###########################################################################################
        # some COOT settings
        coot.set_map_radius(17)
        coot.set_colour_map_rotation_for_map(0)
#        coot.set_colour_map_rotation_on_read_pdb_flag(21)

        self.QualityIndicators = {  'Rcryst':                           '-',
                                    'Rfree':                            '-',
                                    'RfreeTL':                          'gray',
                                    'ResolutionHigh':                   '-',
                                    'ResolutionColor':                  'gray',
                                    'MolprobityScore':                  '-',
                                    'MolprobityScoreColor':             'gray',
                                    'RamachandranOutliers':             '-',
                                    'RamachandranOutliersColor':        'gray',
                                    'RamachandranFavored':              '-',
                                    'RamachandranFavoredColor':         'gray',
                                    'rmsdBonds':                        '-',
                                    'rmsdBondsTL':                      'gray',
                                    'rmsdAngles':                       '-',
                                    'rmsdAnglesTL':                     'gray',
                                    'MatrixWeight':                     '-'   }

        # default refmac parameters
        self.RefmacParams={ 'HKLIN':            '',                 'HKLOUT': '',
                            'XYZIN':            '',                 'XYZOUT': '',
                            'LIBIN':            '',                 'LIBOUT': '',
                            'TLSIN':            '',                 'TLSOUT': '',
                            'TLSADD':           '',
                            'NCYCLES':          '10',
                            'MATRIX_WEIGHT':    'AUTO',
                            'BREF':             '    bref ISOT\n',
                            'TLS':              '',
                            'NCS':              '',
                            'TWIN':             ''    }



    def StartGUI(self):

        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.connect("delete_event", gtk.main_quit)
        self.window.set_border_width(10)
        self.window.set_default_size(400, 800)
        self.window.set_title("Reference Model Builder")
        self.vbox = gtk.VBox()                      # this is the main container

        #################################################################################
        # --- PDB file selection ---
        # checking for pdb files in reference directory
        referenceFiles=[]
        for files in glob.glob(os.path.join(self.reference_directory,'*.pdb')):
            pdbFile=files[files.rfind('/')+1:]
            referenceFiles.append(pdbFile)
        frame = gtk.Frame(label='Select PDB file')
        hbox=gtk.HBox()
        self.cb_select_pdb = gtk.combo_box_new_text()
#        self.cb_select_pdb.connect("changed", self.set_selection_mode)
        for pdbFile in referenceFiles:
            self.cb_select_pdb.append_text(pdbFile)
        hbox.add(self.cb_select_pdb)
        frame.add(hbox)
        self.vbox.pack_start(frame)

        self.load_pdb_file_button = gtk.Button(label="Load")
#        self.load_pdb_file_button.connect("clicked",self.get_samples_to_look_at)
        self.load_pdb_file_button.connect("clicked",self.load_pdb_file)
        hbox.add(self.load_pdb_file_button)
        frame.add(hbox)
        self.vbox.pack_start(frame)

        # SPACER
        self.vbox.add(gtk.Label(' '))

        frame = gtk.Frame(label='MTZ file to refine against')
        hbox=gtk.HBox()
        self.mtzFree=''
        self.mtzFree_label=gtk.Label()
        hbox.add(self.mtzFree_label)
        frame.add(hbox)
        self.vbox.pack_start(frame)

        # SPACER
        self.vbox.add(gtk.Label(' '))

        frame = gtk.Frame(label='MTZ file after refinement')
        hbox=gtk.HBox()
        self.mtzRefine_label=gtk.Label()
        hbox.add(self.mtzRefine_label)
        frame.add(hbox)
        self.vbox.pack_start(frame)



        # SPACER
        self.vbox.add(gtk.Label(' \n '))


        #################################################################################
        # --- ground state mean map ---
        # checking for ground state mean map in reference folder
        self.meanMaps = {}
        for dirs in glob.glob(os.path.join(self.reference_directory,'pandda_*')):
            panddaDir=dirs.split('/')[len(dirs.split('/'))-1]
            for files in glob.glob(os.path.join(dirs,'processed_datasets','*','*ground-state-mean-map.native.ccp4')):
                if os.path.isfile(files):
                    self.meanMaps[panddaDir]=files
                    break

        frame = gtk.Frame(label='Load ground-state-mean-map file')
        hbox=gtk.HBox()
        self.cb_select_mean_map = gtk.combo_box_new_text()
        for item in self.meanMaps:
            self.cb_select_mean_map.append_text(item)
        hbox.add(self.cb_select_mean_map)
        self.load_ground_state_map_button = gtk.Button(label="Load")
        self.load_ground_state_map_button.connect("clicked",self.load_ground_state_map)
        hbox.add(self.load_ground_state_map_button)
        frame.add(hbox)
        self.vbox.pack_start(frame)


        # SPACER
        self.vbox.add(gtk.Label(' \n '))

        # --- Refinement History ---
        frame = gtk.Frame(label='Refinement History')
        self.hbox_for_info_graphics=gtk.HBox()
        self.canvas = FigureCanvas(self.update_plot([0],[0],[0]))
        self.canvas.set_size_request(190, 190)
        self.hbox_for_info_graphics.add(self.canvas)
        frame.add(hbox)
        self.vbox.pack_start(frame)

        #################################################################################
        # --- status window ---
        frame=gtk.Frame(label='Status')
        vbox=gtk.VBox()
        self.spinnerBox=gtk.VBox()
        self.refinementRunning=gtk.Spinner()
        vbox.add(self.spinnerBox)
#        hbox.add(self.refinementRunning)
        self.status_label=gtk.Label()
        vbox.add(self.status_label)
        frame.add(vbox)
        self.status_label.set_text('idle')

#        frame.add(self.status_label)
        self.vbox.pack_start(frame)

        #################################################################################
        # --- Refinement Statistics ---
        # next comes a section which displays some global quality indicators
        # a combination of labels and textview widgets, arranged in a table

        RRfreeLabel_frame=gtk.Frame()
        self.RRfreeLabel = gtk.Label('R/Rfree')
        RRfreeLabel_frame.add(self.RRfreeLabel)
        self.RRfreeValue = gtk.Label(self.QualityIndicators['Rcryst']+'/'+self.QualityIndicators['Rfree'])
        RRfreeBox_frame=gtk.Frame()
        self.RRfreeBox = gtk.EventBox()
        self.RRfreeBox.add(self.RRfreeValue)
        RRfreeBox_frame.add(self.RRfreeBox)

        ResolutionLabel_frame=gtk.Frame()
        self.ResolutionLabel = gtk.Label('Resolution')
        ResolutionLabel_frame.add(self.ResolutionLabel)
        self.ResolutionValue = gtk.Label(self.QualityIndicators['ResolutionHigh'])
        ResolutionBox_frame=gtk.Frame()
        self.ResolutionBox = gtk.EventBox()
        self.ResolutionBox.add(self.ResolutionValue)
        ResolutionBox_frame.add(self.ResolutionBox)

        MolprobityScoreLabel_frame=gtk.Frame()
        self.MolprobityScoreLabel = gtk.Label('MolprobityScore')
        MolprobityScoreLabel_frame.add(self.MolprobityScoreLabel)
        self.MolprobityScoreValue = gtk.Label(self.QualityIndicators['MolprobityScore'])
        MolprobityScoreBox_frame=gtk.Frame()
        self.MolprobityScoreBox = gtk.EventBox()
        self.MolprobityScoreBox.add(self.MolprobityScoreValue)
        MolprobityScoreBox_frame.add(self.MolprobityScoreBox)

        RamachandranOutliersLabel_frame=gtk.Frame()
        self.RamachandranOutliersLabel = gtk.Label('Rama Outliers')
        RamachandranOutliersLabel_frame.add(self.RamachandranOutliersLabel)
        self.RamachandranOutliersValue = gtk.Label(self.QualityIndicators['RamachandranOutliers'])
        RamachandranOutliersBox_frame=gtk.Frame()
        self.RamachandranOutliersBox = gtk.EventBox()
        self.RamachandranOutliersBox.add(self.RamachandranOutliersValue)
        RamachandranOutliersBox_frame.add(self.RamachandranOutliersBox)

        RamachandranFavoredLabel_frame=gtk.Frame()
        self.RamachandranFavoredLabel = gtk.Label('Rama Favored')
        RamachandranFavoredLabel_frame.add(self.RamachandranFavoredLabel)
        self.RamachandranFavoredValue = gtk.Label(self.QualityIndicators['RamachandranFavoredColor'])
        RamachandranFavoredBox_frame=gtk.Frame()
        self.RamachandranFavoredBox = gtk.EventBox()
        self.RamachandranFavoredBox.add(self.RamachandranFavoredValue)
        RamachandranFavoredBox_frame.add(self.RamachandranFavoredBox)

        rmsdBondsLabel_frame=gtk.Frame()
        self.rmsdBondsLabel = gtk.Label('rmsd(Bonds)')
        rmsdBondsLabel_frame.add(self.rmsdBondsLabel)
        self.rmsdBondsValue = gtk.Label(self.QualityIndicators['rmsdBonds'])
        rmsdBondsBox_frame=gtk.Frame()
        self.rmsdBondsBox = gtk.EventBox()
        self.rmsdBondsBox.add(self.rmsdBondsValue)
        rmsdBondsBox_frame.add(self.rmsdBondsBox)

        rmsdAnglesLabel_frame=gtk.Frame()
        self.rmsdAnglesLabel = gtk.Label('rmsd(Angles)')
        rmsdAnglesLabel_frame.add(self.rmsdAnglesLabel)
        self.rmsdAnglesValue = gtk.Label(self.QualityIndicators['rmsdAngles'])
        rmsdAnglesBox_frame=gtk.Frame()
        self.rmsdAnglesBox = gtk.EventBox()
        self.rmsdAnglesBox.add(self.rmsdAnglesValue)
        rmsdAnglesBox_frame.add(self.rmsdAnglesBox)

        MatrixWeightLabel_frame=gtk.Frame()
        self.MatrixWeightLabel = gtk.Label('Matrix Weight')
        MatrixWeightLabel_frame.add(self.MatrixWeightLabel)
        self.MatrixWeightValue = gtk.Label(self.QualityIndicators['MatrixWeight'])
        MatrixWeightBox_frame=gtk.Frame()
        self.MatrixWeightBox = gtk.EventBox()
        self.MatrixWeightBox.add(self.MatrixWeightValue)
        MatrixWeightBox_frame.add(self.MatrixWeightBox)

        outer_frame = gtk.Frame()
        hbox = gtk.HBox()

        frame = gtk.Frame()
        self.table_left  = gtk.Table(8, 2, False)
        self.table_left.attach(RRfreeLabel_frame,                 0, 1, 0, 1)
        self.table_left.attach(ResolutionLabel_frame,             0, 1, 1, 2)
        self.table_left.attach(MolprobityScoreLabel_frame,        0, 1, 2, 3)
        self.table_left.attach(RamachandranOutliersLabel_frame,   0, 1, 3, 4)
        self.table_left.attach(RamachandranFavoredLabel_frame,    0, 1, 4, 5)
        self.table_left.attach(rmsdBondsLabel_frame,              0, 1, 5, 6)
        self.table_left.attach(rmsdAnglesLabel_frame,             0, 1, 6, 7)
        self.table_left.attach(MatrixWeightLabel_frame,           0, 1, 7, 8)
        self.table_left.attach(RRfreeBox_frame,                   1, 2, 0, 1)
        self.table_left.attach(ResolutionBox_frame,               1, 2, 1, 2)
        self.table_left.attach(MolprobityScoreBox_frame,          1, 2, 2, 3)
        self.table_left.attach(RamachandranOutliersBox_frame,     1, 2, 3, 4)
        self.table_left.attach(RamachandranFavoredBox_frame,      1, 2, 4, 5)
        self.table_left.attach(rmsdBondsBox_frame,                1, 2, 5, 6)
        self.table_left.attach(rmsdAnglesBox_frame,               1, 2, 6, 7)
        self.table_left.attach(MatrixWeightBox_frame,             1, 2, 7, 8)
        frame.add(self.table_left)
        hbox.add(frame)

        outer_frame.add(hbox)
        self.vbox.add(outer_frame)

        button = gtk.Button(label="Show MolProbity to-do list")
        button.connect("clicked",self.show_molprobity_to_do)
        self.vbox.add(button)
        self.vbox.pack_start(frame)

        # SPACER
        self.vbox.add(gtk.Label(' '))

        # --- refinement & options ---
        self.hbox_for_refinement=gtk.HBox()
        self.REFINEbutton = gtk.Button(label="Refine")
        self.RefinementParamsButton = gtk.Button(label="refinement parameters")
        self.REFINEbutton.connect("clicked",self.REFINE)
        self.hbox_for_refinement.add(self.REFINEbutton)
        self.RefinementParamsButton.connect("clicked",self.RefinementParams)
        self.hbox_for_refinement.add(self.RefinementParamsButton)
        self.vbox.add(self.hbox_for_refinement)

        # --- CANCEL button ---
        self.CANCELbutton = gtk.Button(label="CANCEL")
        self.CANCELbutton.connect("clicked", self.CANCEL)
        self.vbox.add(self.CANCELbutton)

        self.window.add(self.vbox)
        self.window.show_all()

    def CANCEL(self,widget):
        self.window.destroy()


    def RefreshData(self):

        # initialize Refinement library
        self.Refine=XChemRefine.Refine(self.reference_directory,self.refinementDir,'dummy_compound_ID','dummy_database')
        self.Serial=self.Refine.GetSerial()

        #########################################################################################
        # history
        # if the structure was previously refined, try to read the parameters
        if self.Serial > 1:
            self.RefmacParams=self.Refine.ParamsFromPreviousCycle(self.Serial-1)
            refinement_cycle,Rfree,Rcryst=self.Refine.GetRefinementHistory()
            self.canvas = FigureCanvas(self.update_plot(refinement_cycle,Rfree,Rcryst))
        else:
            self.canvas = FigureCanvas(self.update_plot([0],[0],[0]))  # a gtk.DrawingArea
        self.canvas.set_size_request(190, 190)
        self.hbox_for_info_graphics.add(self.canvas)
        self.canvas.show()

        #########################################################################################
        # update Quality Indicator table
        print self.QualityIndicators
        try:
            self.RRfreeValue.set_label(  str(round(float(self.QualityIndicators['Rcryst']),3)) +' / '+str(round(float(self.QualityIndicators['Rfree']),3)))
        except ValueError:
            self.RRfreeValue.set_label('-')

        try:
            self.RRfreeBox.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse(self.QualityIndicators['RfreeTL']))
        except ValueError:
            pass
        self.ResolutionValue.set_label(self.QualityIndicators['ResolutionHigh'])
        try:
            self.ResolutionBox.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse(self.QualityIndicators['ResolutionColor']))
        except ValueError:
            pass
        self.MolprobityScoreValue.set_label(self.QualityIndicators['MolprobityScore'])
        try:
            self.MolprobityScoreBox.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse(self.QualityIndicators['MolprobityScoreColor']))
        except ValueError:
            pass
        self.RamachandranOutliersValue.set_label(self.QualityIndicators['RamachandranOutliers'])
        try:
            self.RamachandranOutliersBox.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse(self.QualityIndicators['RamachandranOutliersColor']))
        except ValueError:
            pass
        self.RamachandranFavoredValue.set_label(self.QualityIndicators['RamachandranFavoredColor'])
        try:
            self.RamachandranFavoredBox.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse(self.QualityIndicators['RamachandranFavoredColor']))
        except ValueError:
            pass
        self.rmsdBondsValue.set_label(self.QualityIndicators['rmsdBonds'])
        try:
            self.rmsdBondsBox.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse(self.QualityIndicators['rmsdBondsTL']))
        except ValueError:
            pass
        self.rmsdAnglesValue.set_label(self.QualityIndicators['rmsdAngles'])
        try:
            self.rmsdAnglesBox.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse(self.QualityIndicators['rmsdAnglesTL']))
        except ValueError:
            pass
        self.MatrixWeightValue.set_label(self.QualityIndicators['MatrixWeight'])


    def REFINE(self,widget):

        if self.job_running:
            coot.info_dialog('*** refinement in progress ***')
            return None

        #######################################################
        # create folder for new refinement cycle and check if free.mtz exists
        if not os.path.isdir(os.path.join(self.reference_directory,self.refinementDir)):
            os.mkdir(os.path.join(self.reference_directory,self.refinementDir))
        if not os.path.isdir(os.path.join(self.reference_directory,self.refinementDir,'Refine_'+str(self.Serial))):
            os.mkdir(os.path.join(self.reference_directory,self.refinementDir,'Refine_'+str(self.Serial)))
        if not os.path.isfile(os.path.join(self.reference_directory,self.refinementDir,self.refinementDir+'.free.mtz')):
            os.chdir(os.path.join(self.reference_directory,self.refinementDir))
            os.symlink(self.mtzFree,self.refinementDir+'.free.mtz')

        #######################################################
        # write PDB file
        # now take protein pdb file and write it to newly create Refine_<serial> folder
        # note: the user has to make sure that the ligand file was merged into main file
        for item in coot_utils_XChem.molecule_number_list():
            if coot.molecule_name(item) in self.pdbFile:
                coot.write_pdb_file(item,os.path.join(self.reference_directory,self.refinementDir,'Refine_'+str(self.Serial),'in.pdb'))
                break

        self.Refine.RunRefmac(self.Serial,self.RefmacParams,self.external_software,self.xce_logfile)
        self.spinnerBox.add(self.refinementRunning)
        self.refinementRunning.start()
        self.status_label.set_text('Refinement running...')

        # launch refinement
        time.sleep(1)   # waiting 1s to make sure that REFINEMENT_IN_PROGRESS is written
        self.source_id = gobject.timeout_add(100, self.wait_for_refined_pdb)

    def wait_for_refined_pdb(self):
        self.spinnerBox.add(self.refinementRunning)
        self.refinementRunning.show()
        self.refinementRunning.start()
        if not os.path.isfile(os.path.join(self.reference_directory,self.refinementDir,'REFINEMENT_IN_PROGRESS')):
            self.job_running=False
            self.end_thread()
        return True

    def end_thread(self):
        self.refinementRunning.stop()
        self.spinnerBox.remove(self.refinementRunning)
        self.status_label.set_text('idle')
        gobject.source_remove(self.source_id)
        self.update_pdb_mtz_files('')



    def RefinementParams(self,widget):
        print '\n==> XCE: changing refinement parameters'
        self.RefmacParams=self.Refine.RefinementParams(self.RefmacParams)

    def set_selection_mode(self,widget):
        self.selection_mode=widget.get_active_text()


    def load_pdb_file(self,widget):
        pdbRoot=self.cb_select_pdb.get_active_text()
        if self.pdbFile != '':
            self.Logfile.error('sorry, you need to close the current instance of COOT and start again')

        self.refinementDir=pdbRoot.replace('.pdb','')
        self.update_pdb_mtz_files(pdbRoot)

    def update_pdb_mtz_files(self,pdbRoot):
        # first remove all pdb and mtz files from memory
        self.Logfile.insert('removing all PDB and MTZ files from memory')
        if len(coot_utils_XChem.molecule_number_list()) > 0:
            for item in coot_utils_XChem.molecule_number_list():
                if coot.molecule_name(item).endswith('.pdb') or coot.molecule_name(item).endswith('.mtz'):
                    self.Logfile.insert('removing %s' %coot.molecule_name(item))
                    coot.close_molecule(item)

        coot.set_nomenclature_errors_on_read("ignore")
        # first we check if there is a refinement folder and the respective refine.pdb
        # from previous refinement cycles
        if os.path.isfile(os.path.join(self.reference_directory,self.refinementDir,'refine.pdb')):
            self.pdbFile=os.path.join(self.reference_directory,self.refinementDir,'refine.pdb')
        elif os.path.isfile(os.path.join(self.reference_directory,pdbRoot)):
            self.pdbFile=os.path.join(self.reference_directory,pdbRoot)
        else:
            self.Logfile.error('cannot find PDB file')

        if self.pdbFile != '':
            os.chdir(os.path.join(self.reference_directory,self.refinementDir))
            coot.set_colour_map_rotation_on_read_pdb(0)
            imol=coot.handle_read_draw_molecule_with_recentre(self.pdbFile,0)
            self.QualityIndicators=XChemUtils.parse().PDBheader(os.path.join(self.pdbFile))
            self.QualityIndicators.update(XChemUtils.logtools(os.path.join(self.reference_directory,self.refinementDir,'refine_molprobity.log')).phenix_molprobity())
            self.QualityIndicators.update(XChemUtils.logtools(os.path.join(self.reference_directory,self.refinementDir,'Refine_'+str(self.Serial),'refmac.log')).refmac_log())
            self.mol_dict['protein']=imol


        self.mtzFree=''
        if os.path.isfile(os.path.join(self.reference_directory,self.pdbFile.replace('.pdb','')+'.free.mtz')):
            self.mtzFree=os.path.join(self.reference_directory,self.pdbFile.replace('.pdb','')+'.free.mtz')
            self.mtzFree_label.set_text(self.pdbFile.replace('.pdb','')+'.free.mtz')
            self.REFINEbutton.set_sensitive(True)
        else:
            self.mtzFree_label.set_text('missing file')
            self.Logfile.error('cannot find file with F,SIGF and FreeR_flag; cannot start refinement')
            self.REFINEbutton.set_sensitive(False)

        self.mtzRefine=''
        if os.path.isfile(os.path.join(self.reference_directory,self.refinementDir,'refine.mtz')):
            self.mtzRefine=os.path.join(self.reference_directory,self.refinementDir,'refine.mtz')
            self.mtzRefine_label.set_text(mtzFree)
        else:
            self.mtzRefine_label.set_text('missing file')
            self.Logfile.warning('cannot find file with F,SIGF and FreeR_flag; cannot start refinement')

        self.RefreshData()

    def load_ground_state_map(self,widget):
        # first remove all ground state maps files
        if len(coot_utils_XChem.molecule_number_list()) > 0:
            for item in coot_utils_XChem.molecule_number_list():
                if 'ground-state-mean-map' in coot.molecule_name(item):
                    coot.close_molecule(item)

        for item in self.meanMaps:
            if item==self.cb_select_mean_map.get_active_text():
                self.ground_state_mean_map=self.meanMaps[item]
                break

        coot.set_colour_map_rotation_on_read_pdb(0)
        coot.handle_read_ccp4_map((self.ground_state_mean_map),0)
        for imol in coot_utils_XChem.molecule_number_list():
            if self.ground_state_mean_map in coot.molecule_name(imol):
                coot.set_contour_level_in_sigma(imol,2)
                coot.set_last_map_colour(0.74,0.44,0.02)

    def show_molprobity_to_do(self,widget):
        if os.path.isfile(os.path.join(self.reference_directory,self.refinementDir,'Refine_'+str(self.Serial-1),'molprobity_coot.py')):
            coot.run_script(os.path.join(self.reference_directory,self.refinementDir,'Refine_'+str(self.Serial-1),'molprobity_coot.py'))
        else:
            print '==> XCE: cannot find '+os.path.join(self.reference_directory,self.xtalID,'Refine_'+str(self.Serial-1),'molprobity_coot.py')

    def update_plot(self,refinement_cycle,Rfree,Rcryst):
        fig = Figure(figsize=(2, 2), dpi=50)
        Plot = fig.add_subplot(111)
        Plot.set_ylim([0,max(Rcryst+Rfree)])
        Plot.set_xlabel('Refinement Cycle',fontsize=12)
        Plot.plot(refinement_cycle,Rfree,label='Rfree',linewidth=2)
        Plot.plot(refinement_cycle,Rcryst,label='Rcryst',linewidth=2)
        Plot.legend(bbox_to_anchor=(0., 1.02, 1., .102), loc=3,
                ncol=2, mode="expand", borderaxespad=0.,fontsize=12)
        return fig



if __name__=='__main__':
    GUI().StartGUI()