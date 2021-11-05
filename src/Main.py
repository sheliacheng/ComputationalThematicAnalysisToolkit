'''Main Program for MachineThematicAnalysisToolkit'''
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import tempfile
import multiprocessing
import psutil
from datetime import datetime

import wx
from wx.adv import HyperlinkCtrl
import wx.lib.agw.labelbook as LB
import External.wxPython.labelbook_fix as LB_fix

import RootApp
import Common.Constants as Constants
import Common.CustomEvents as CustomEvents
import Common.Objects.Samples as Samples
import Common.Database as Database
from Common.GUIText import Main as GUIText
import Common.Notes as cn
import Collection.ModuleCollection as CollectionModule
import Filtering.ModuleFiltering as FilteringModule
import Sampling.ModuleSampling as SamplingModule
import Coding.ModuleCoding as CodingModule
import Review.ModuleReviewing as ReviewingModule
import Report.ModuleReporting as ReportingModule
import MainThreads

class MainFrame(wx.Frame):
    '''the Main GUI'''
    def __init__(self, parent, ID, title, pool,
                 pos=wx.DefaultPosition, size=wx.DefaultSize, style=wx.DEFAULT_FRAME_STYLE):
        logger = logging.getLogger(__name__+".MainFrame.__init__")
        logger.info("Starting")
        wx.Frame.__init__(self, parent, ID, title, pos, size, style)

        self.SetMinSize(wx.Size(400, 400))
        self.Maximize(True)

        #multiprocessing controls
        self.pool = pool
        self.pool_num = self.pool._processes
        self.multiprocessing_inprogress_flag = False

        self.datasets = {}
        self.samples = {}
        self.model_iter = 0
        self.codes = {}
        self.save_path = ''
        self.current_workspace = tempfile.TemporaryDirectory(dir=Constants.CURRENT_WORKSPACE_PATH)
        Database.DatabaseConnection(self.current_workspace.name).Create()
        
        self.last_load_dt = datetime.now()
        self.load_thread = None
        self.progress_dialog = None
        self.progress_dialog_references = 0
        self.closing = False
        self.autosave_flag = False

        self.options_dialog = None
        self.about_dialog = None

        self.codeconnections_dialogs = {}
        self.document_dialogs = {} #TODO


        #Workspace's Options
        self.options_dict = {'multipledatasets_mode': False,
                             'adjustable_label_fields_mode': False,
                             'adjustable_computation_fields_mode': False}
        #used to control order of modules. not currently used but needed in future customization options to support other thematic analysis approaches
        self.module_order = ['collection',
                             'filtering',
                             'sampling',
                             'coding',
                             #'reviewing',
                             'reporting']

        #frame and notebook for notes to make accessible when moving between modules
        self.notes_frame = wx.Frame(self,
                                    title=GUIText.NOTES_LABEL,
                                    style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
        self.notes_notebook = cn.NotesNotebook(self.notes_frame)
        #Project's General Notes panel
        self.notes_panel = cn.NotesPanel(self.notes_notebook, None)
        self.notes_notebook.AddPage(self.notes_panel, GUIText.GENERAL_LABEL)

        #notebook for managing layout and tabs of modules
        self.main_notebook = LB_fix.LabelBook(self, agwStyle=LB.INB_LEFT|LB.INB_SHOW_ONLY_TEXT|LB.INB_FIT_LABELTEXT, size=self.GetSize())
        self.main_notebook.SetColour(LB.INB_TAB_AREA_BACKGROUND_COLOUR, self.GetBackgroundColour())

        #Modules
        self.collection_module = CollectionModule.CollectionPanel(self.main_notebook, size=self.GetSize())
        self.main_notebook.InsertPage(self.module_order.index('collection'), self.collection_module, GUIText.COLLECTION_LABEL)
        self.filtering_module = FilteringModule.FilteringNotebook(self.main_notebook, size=self.GetSize())
        self.main_notebook.InsertPage(self.module_order.index('filtering'), self.filtering_module, GUIText.FILTERING_LABEL)
        self.sampling_module = SamplingModule.SamplingNotebook(self.main_notebook, size=self.GetSize())
        self.main_notebook.InsertPage(self.module_order.index('sampling'), self.sampling_module, GUIText.SAMPLING_LABEL)
        self.coding_module = CodingModule.CodingNotebook(self.main_notebook, size=self.GetSize())
        self.main_notebook.InsertPage(self.module_order.index('coding'), self.coding_module, GUIText.CODING_LABEL)
        #self.reviewing_module = ReviewingModule.ReviewingPanel(self.main_notebook, size=self.GetSize())
        #self.main_notebook.InsertPage(self.module_order.index('reviewing'), self.reviewing_module, GUIText.REVIEWING_LABEL)
        self.reporting_module = ReportingModule.ReportingPanel(self.main_notebook, size=self.GetSize())
        self.main_notebook.InsertPage(self.module_order.index('reporting'), self.reporting_module, GUIText.REPORTING_LABEL)
        
        #Sizer for Frame
        self.panel_sizer = wx.BoxSizer(wx.VERTICAL)
        self.panel_sizer.Add(self.main_notebook, 1, wx.EXPAND)
        self.SetSizer(self.panel_sizer)

        #Actions For Main Frame
        self.Bind(wx.EVT_CLOSE, self.OnCloseStart)

        #Actions For Notes Frame
        self.notes_frame.Bind(wx.EVT_CLOSE, self.OnNotesClose)

        #Initializing Static Menus
        self.menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        new_file_menuitem = file_menu.Append(wx.ID_ANY,
                                             GUIText.NEW,
                                             GUIText.NEW_TOOLTIP)
        self.Bind(wx.EVT_MENU, self.OnNew, new_file_menuitem)
        file_menu.AppendSeparator()
        resume_file_menuitem = file_menu.Append(wx.ID_ANY,
                                             GUIText.RESUME,
                                             GUIText.RESUME_TOOLTIP)
        self.Bind(wx.EVT_MENU, self.OnRestoreLoadStart, resume_file_menuitem)
        file_menu.AppendSeparator()
        load_file_menuitem = file_menu.Append(wx.ID_OPEN,
                                              GUIText.LOAD,
                                              GUIText.LOAD_TOOLTIP)
        self.Bind(wx.EVT_MENU, self.OnLoadStart, load_file_menuitem)
        CustomEvents.LOAD_EVT_RESULT(self, self.OnLoadEnd)
        save_file_menuitem = file_menu.Append(wx.ID_SAVE,
                                              GUIText.SAVE,
                                              GUIText.SAVE_TOOLTIP)
        self.Bind(wx.EVT_MENU, self.OnSaveStart, save_file_menuitem)
        CustomEvents.SAVE_EVT_RESULT(self, self.OnSaveEnd)
        saveas_file_menuitem = file_menu.Append(wx.ID_SAVEAS,
                                                GUIText.SAVE_AS,
                                                GUIText.SAVE_AS_TOOLTIP)
        self.Bind(wx.EVT_MENU, self.OnSaveAs, saveas_file_menuitem)
        file_menu.AppendSeparator()
        exit_file_menuitem = file_menu.Append(wx.ID_EXIT,
                                         GUIText.EXIT,
                                         GUIText.EXIT_TOOLTIP)
        self.Bind(wx.EVT_MENU, self.OnCloseStart, exit_file_menuitem)
        self.menu_bar.Append(file_menu, GUIText.FILE_MENU)

        self.actions_menu = wx.Menu()

        self.toggle_notes_menuitem = self.actions_menu.Append(wx.ID_ANY,
                                                              GUIText.SHOW_HIDE + GUIText.NOTES_LABEL,
                                                              kind=wx.ITEM_CHECK)
        self.Bind(wx.EVT_MENU, self.OnToggleNotes, self.toggle_notes_menuitem)
        
        self.actions_menu.AppendSeparator()

        #commented out modules that do not use this menu type at this time. readd once used
        #self.collection_module.actions_menu_menuitem = self.actions_menu.AppendSubMenu(self.collection_module.actions_menu, GUIText.COLLECTION_LABEL)
        self.filtering_module.actions_menu_menuitem = self.actions_menu.AppendSubMenu(self.filtering_module.actions_menu, GUIText.FILTERING_MENU_LABEL)
        #self.sampling_module.actions_menu_menuitem = self.actions_menu.AppendSubMenu(self.sampling_module.actions_menu, GUIText.SAMPLING_MENU_LABEL)
        self.coding_module.actions_menu_menuitem = self.actions_menu.AppendSubMenu(self.coding_module.actions_menu, GUIText.CODING_LABEL)
        #self.reviewing_module.actions_menu_menuitem = self.actions_menu.AppendSubMenu(self.reviewing_module.actions_menu, GUIText.REVIEWING_LABEL)
        #self.reporting_module.actions_menu_menuitem = self.actions_menu.AppendSubMenu(self.reporting_module.actions_menu, GUIText.REPORTING_LABEL)
        self.menu_bar.Append(self.actions_menu, GUIText.ACTIONS)

        if platform.system() == 'Darwin':
            app_menu = self.menu_bar.OSXGetAppleMenu()
            about_menuitem = app_menu.Insert(0, wx.ID_ANY, GUIText.ABOUT)
            self.Bind(wx.EVT_MENU, self.OnAbout, about_menuitem)
            app_menu.InsertSeparator(1)
            options_file_menuitem = app_menu.Insert(2, wx.ID_ANY,
                                                    GUIText.OPTIONS_LABEL)
            self.Bind(wx.EVT_MENU, self.OnOptions, options_file_menuitem)
            app_menu.InsertSeparator(3)
        else:
            #Help menu
            self.help_menu = wx.Menu()
            about_menuitem = self.help_menu.Append(wx.ID_ANY, GUIText.ABOUT)
            self.Bind(wx.EVT_MENU, self.OnAbout, about_menuitem)
            self.menu_bar.Append(self.help_menu, GUIText.HELP)
            #Option Menu Item
            options_file_menuitem = file_menu.Insert(0, wx.ID_ANY,
                                                    GUIText.OPTIONS_LABEL)
            self.Bind(wx.EVT_MENU, self.OnOptions, options_file_menuitem)
            file_menu.InsertSeparator(1)
        
        self.SetMenuBar(self.menu_bar)

        CustomEvents.EVT_PROGRESS(self, self.OnProgress)

        self.Layout()
        self.Fit()
        self.Show(True)

        logger.info("Finished")

    #Functions called by actions on the GUI (menus or buttons)
    def OnToggleNotes(self, event):
        logger = logging.getLogger(__name__+".MainFrame.OnToggleNotes")
        logger.info("Starting")
        if self.toggle_notes_menuitem.IsChecked():
            self.notes_frame.Show()
        else:
            self.notes_frame.Hide()
        logger.info("Finished")

    def OnNotesClose(self, event):
        logger = logging.getLogger(__name__+".MainFrame.OnNotesClose")
        logger.info("Starting")
        self.notes_frame.Hide()
        self.toggle_notes_menuitem.Check(False)
        logger.info("Finished")
    
    def OnOptions(self, event):
        logger = logging.getLogger(__name__+".MainFrame.OnOptions")
        logger.info("Starting")
        if self.options_dialog == None:
            self.options_dialog = OptionsDialog(self)
            self.options_dialog
        self.options_dialog.Show()
        self.options_dialog.SetFocus()
        logger.info("Finished")

    def OnAbout(self, event):
        logger = logging.getLogger(__name__+".MainFrame.OnAbout")
        logger.info("Starting")
        if self.about_dialog == None:
            self.about_dialog = AboutDialog(self)
        self.about_dialog.Show()
        self.about_dialog.SetFocus()
        logger.info("Finished")

    def OnNew(self, event):
        logger = logging.getLogger(__name__+".MainFrame.OnNew")
        logger.info("Starting")
        if self.multiprocessing_inprogress_flag:
            wx.MessageBox(GUIText.MULTIPROCESSING_WARNING_MSG,
                          GUIText.WARNING, wx.OK | wx.ICON_WARNING)
        else:
            #check if current workspace is not recently saved
            check_flag = False
            if not check_flag and len(self.datasets) != 0:
                for key in self.datasets:
                    if self.datasets[key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if not check_flag and len(self.samples) != 0:
                for key in self.samples:
                    if self.samples[key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if not check_flag and len(self.codes) != 0:
                for key in self.codes:
                    if self.codes[key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if check_flag:
                confirm_dialog = wx.MessageDialog(self, GUIText.NEW_WARNING,
                                                GUIText.CONFIRM_REQUEST, wx.ICON_QUESTION | wx.OK | wx.CANCEL)
                confirm_dialog.SetOKLabel(GUIText.PROCEED_ANYWAYS)
                confirm_flag = confirm_dialog.ShowModal()
            else:
                confirm_flag = wx.ID_OK
            if confirm_flag == wx.ID_OK:
                self.CreateProgressDialog(title=GUIText.NEW_BUSY_LABEL,
                                        warning=GUIText.SIZE_WARNING_MSG,
                                        freeze=True)
                self.PulseProgressDialog(GUIText.NEW_BUSY_MSG)

                self.Freeze()

                #reset objects
                for key in self.codeconnections_dialogs:
                    self.codeconnections_dialogs[key].Destroy()    
                self.codeconnections_dialogs.clear()
                for key in self.document_dialogs:
                    self.document_dialogs[key].Destroy()    
                self.codeconnections_dialogs.clear()
                for key in self.codes:
                    self.codes[key].DestroyObject()
                self.codes.clear()
                for key in self.samples:
                    self.samples[key].DestroyObject()
                self.samples.clear()
                for key in self.datasets:
                    self.datasets[key].DestroyObject()
                self.datasets.clear()
                

                self.save_path = ''
                self.current_workspace.cleanup()
                self.current_workspace = tempfile.TemporaryDirectory(dir=Constants.CURRENT_WORKSPACE_PATH)
                Database.DatabaseConnection(self.current_workspace.name).Create()
            
                self.last_load_dt = datetime.now()

                self.DatasetsUpdated(autosave=False)
                self.SamplesUpdated()
                self.DocumentsUpdated(self)
                #TODO investigate error that occurs when a code is selected when new is clicked
                self.CodesUpdated()

                self.SetTitle(GUIText.APP_NAME+" - "+GUIText.UNSAVED)

                self.Thaw()

                self.CloseProgressDialog(thaw=True)
        logger.info("Finished")
    
    def OnLoadStart(self, event):
        #start up load thread that performs all backend load operations that take a long time
        '''Menu Function for loading data'''
        logger = logging.getLogger(__name__+".MainFrame.OnLoadStart")
        logger.info("Starting")
        
        check_flag = False
        #check if current workspace is not recently saved
        if not check_flag and len(self.datasets) != 0:
            for key in self.datasets:
                if self.datasets[key].last_changed_dt > self.last_load_dt:
                    check_flag = True
        if not check_flag and len(self.samples) != 0:
            for key in self.samples:
                if self.samples[key].last_changed_dt > self.last_load_dt:
                    check_flag = True
        if not check_flag and len(self.codes) != 0:
            for key in self.codes:
                if self.codes[key].last_changed_dt > self.last_load_dt:
                    check_flag = True
        if check_flag:
            confirm_dialog = wx.MessageDialog(self, GUIText.LOAD_WARNING,
                                                GUIText.CONFIRM_REQUEST, wx.ICON_QUESTION | wx.OK | wx.CANCEL)
            confirm_dialog.SetOKLabel(GUIText.LOAD_ANYWAYS)
            confirm_flag = confirm_dialog.ShowModal()
        else:
            confirm_flag = wx.ID_OK
        if confirm_flag == wx.ID_OK:
            #ask the user what workspace to open
            with wx.FileDialog(self,
                            message=GUIText.LOAD_REQUEST,
                            defaultDir=Constants.SAVED_WORKSPACES_PATH,
                            style=wx.DD_DEFAULT_STYLE|wx.FD_FILE_MUST_EXIST|wx.FD_OPEN,
                            wildcard="*.mta") as file_dialog:
                if file_dialog.ShowModal() == wx.ID_OK:
                    self.CreateProgressDialog(title=GUIText.LOAD_BUSY_LABEL,
                                            warning=GUIText.SIZE_WARNING_MSG,
                                            freeze=True)
                    self.PulseProgressDialog(GUIText.LOAD_BUSY_MSG)

                    self.save_path = file_dialog.GetPath()
                    self.PulseProgressDialog(GUIText.LOAD_BUSY_MSG_FILE + str(self.save_path))
                    logger.info("loading file: %s", self.save_path)
                    self.SetTitle(GUIText.APP_NAME+" - "+file_dialog.GetFilename())

                    #reset objects
                    for key in self.codes:
                        self.codes[key].DestroyObject()
                    self.codes.clear()
                    for key in self.samples:
                        self.samples[key].DestroyObject()
                    self.samples.clear()
                    for key in self.datasets:
                        self.datasets[key].DestroyObject()
                    self.datasets.clear()

                    #update gui based on reset objects to prevent errors
                    self.DatasetsUpdated(autosave=False)
                    self.SamplesUpdated()
                    self.DocumentsUpdated(self)
                    self.CodesUpdated()

                    self.current_workspace.cleanup()
                    self.current_workspace = tempfile.TemporaryDirectory(dir=Constants.CURRENT_WORKSPACE_PATH)

                    self.last_load_dt = datetime.now()
                    self.load_thread = MainThreads.LoadThread(self, self.save_path, self.current_workspace.name)
        logger.info("Finished")
    
    def OnRestoreLoadStart(self, event):
        '''function to resume from last autosave'''
        logger = logging.getLogger(__name__+".MainFrame.OnRestoreLoadStart")
        logger.info("Starting")

        if os.path.isdir(Constants.AUTOSAVE_PATH):
            check_flag = False
            #check if current workspace is not recently saved
            if not check_flag and len(self.datasets) != 0:
                for dataset_key in self.datasets:
                    if self.datasets[dataset_key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if not check_flag and len(self.samples) != 0:
                for sample_key in self.samples:
                    if self.samples[sample_key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if not check_flag and len(self.codes) != 0:
                for code_key in self.codes:
                    if self.codes[code_key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if check_flag:
                confirm_dialog = wx.MessageDialog(self, GUIText.LOAD_WARNING,
                                                    GUIText.CONFIRM_REQUEST, wx.ICON_QUESTION | wx.OK | wx.CANCEL)
                confirm_dialog.SetOKLabel(GUIText.LOAD_ANYWAYS)
                confirm_flag = confirm_dialog.ShowModal()
            else:
                confirm_flag = wx.ID_OK
            if confirm_flag == wx.ID_OK:
                self.CreateProgressDialog(title=GUIText.LOAD_BUSY_LABEL,
                                        warning=GUIText.SIZE_WARNING_MSG,
                                        freeze=True)
                self.PulseProgressDialog(GUIText.LOAD_BUSY_MSG)

                self.save_path = ""
                self.PulseProgressDialog(GUIText.LOAD_BUSY_MSG_FILE + str(Constants.AUTOSAVE_PATH))
                logger.info("loading file: %s", Constants.AUTOSAVE_PATH)
                self.SetTitle(GUIText.APP_NAME+" - Last AutoSave")

                #reset objects
                for key in self.codes:
                    self.codes[key].DestroyObject()
                self.codes.clear()
                for key in self.samples:
                    self.samples[key].DestroyObject()
                self.samples.clear()
                for key in self.datasets:
                    self.datasets[key].DestroyObject()
                self.datasets.clear()

                #update gui based on reset objects to prevent errors
                self.DatasetsUpdated(autosave=False)
                self.SamplesUpdated()
                self.DocumentsUpdated(self)
                self.CodesUpdated()

                self.current_workspace.cleanup()
                self.current_workspace = tempfile.TemporaryDirectory(dir=Constants.CURRENT_WORKSPACE_PATH)

                self.last_load_dt = datetime.now()
                self.load_thread = MainThreads.LoadThread(self, Constants.AUTOSAVE_PATH, self.current_workspace.name, restoreload=True)
        else:
            wx.MessageBox(GUIText.NO_AUTOSAVE_ERROR)
        logger.info("Finished")

    def OnLoadEnd(self, event):
        logger = logging.getLogger(__name__+".MainFrame.OnLoadEnd")
        logger.info("Starting")
        #once load thread has finished loading data files into memory run the GUI with the loaded data
        
        saved_data = event.data['config']

        self.ModeChange()
        
        self.datasets.update(event.data['datasets'])
        self.samples.update(event.data['samples'])
        self.codes.update(event.data['codes'])
        self.model_iter = saved_data['model_iter']
        self.options_dict = saved_data['options']

        self.collection_module.Load(saved_data['collection_module'])
        self.filtering_module.Load(saved_data['filtering_module'])
        self.sampling_module.Load(saved_data['sampling_module'])
        self.coding_module.Load(saved_data['coding_module'])
        #self.reviewing_module.Load(saved_data['reviewing_module'])
        self.reporting_module.Load(saved_data['reporting_module'])

        self.toggle_notes_menuitem.Check(check=saved_data['notes_check'])
        self.OnToggleNotes(None)
        self.notes_panel.Load(saved_data['notes'])

        self.load_thread.join()
        self.load_thread = None
        self.CloseProgressDialog(thaw=True)
        logger.info("Finished")

    def OnSaveAs(self, event):
        '''Menu Function for creating new save of data'''
        logger = logging.getLogger(__name__+".MainFrame.OnSaveAs")
        logger.info("Starting")

        with wx.FileDialog(self,
                          message=GUIText.SAVE_AS_REQUEST,
                          defaultDir=Constants.SAVED_WORKSPACES_PATH,
                          style=wx.DD_DEFAULT_STYLE|wx.FD_SAVE,
                          wildcard="*.mta") as file_dialog:
            if file_dialog.ShowModal() == wx.ID_OK:
                self.save_path = file_dialog.GetPath()
                self.SetTitle(GUIText.APP_NAME+" - "+file_dialog.GetFilename())
                try:
                    self.last_load_dt = datetime(1990, 1, 1)
                    
                    self.OnSaveStart(event)
                except IOError:
                    wx.LogError(GUIText.SAVE_AS_FAILURE + self.save_path)
                    logger.error("Failed to save in chosen directory[%s]", self.save_path)
            else:
                if self.closing:
                    self.closing = False
                    self.CloseProgressDialog(thaw=True, message=GUIText.CANCELED)

        logger.info("Finished")

    def OnSaveStart(self, event):
        '''Menu Function for updating save of data'''
        logger = logging.getLogger(__name__+".MainFrame.OnSave")
        logger.info("Starting")
        if self.save_path == '':
            self.OnSaveAs(event)
        else:
            self.CreateProgressDialog(title=GUIText.SAVE_BUSY_LABEL,
                                      warning=GUIText.SIZE_WARNING_MSG,
                                      freeze=True)
            self.PulseProgressDialog(GUIText.SAVE_BUSY_MSG)

            self.PulseProgressDialog(GUIText.SAVE_BUSY_MSG_FILE + str(self.save_path))
            logger.info("saving file: %s", self.save_path)

            self.PulseProgressDialog(GUIText.SAVE_BUSY_MSG_NOTES)
            notes_text = self.notes_notebook.Save()

            self.PulseProgressDialog(GUIText.SAVE_BUSY_MSG_CONFIG)
            config_data = {}
            config_data['notes_check'] = self.toggle_notes_menuitem.IsChecked()
            config_data['notes'] = self.notes_panel.Save()
            config_data['datasets'] = list(self.datasets.keys())
            config_data['options'] = self.options_dict
            config_data['samples'] = list(self.samples.keys())
            config_data['model_iter'] = self.model_iter
            config_data['codes'] = True
            config_data['collection_module'] = self.collection_module.Save()
            config_data['filtering_module'] = self.filtering_module.Save()
            config_data['sampling_module'] = self.sampling_module.Save()
            config_data['coding_module'] = self.coding_module.Save()
            #config_data['reviewing_module'] = self.reviewing_module.Save()
            config_data['reporting_module'] = self.reporting_module.Save()

            self.save_thread = MainThreads.SaveThread(self, self.save_path, self.current_workspace.name, config_data, self.datasets, self.samples, self.codes, notes_text, self.last_load_dt)

    def AutoSaveStart(self):
        '''function for auto saving data after completing important operations'''
        logger = logging.getLogger(__name__+".MainFrame.OnAutoSaveStart")
        logger.info("Starting")
        self.autosave_flag = True
        self.CreateProgressDialog(title=GUIText.SAVE_BUSY_LABEL,
                                  warning=GUIText.SIZE_WARNING_MSG,
                                  freeze=True)
        self.PulseProgressDialog(GUIText.AUTO_SAVE_BUSY_MSG)
        logger.info("auto saving workspace to [%s]", Constants.AUTOSAVE_PATH)

        notes_text = self.notes_notebook.Save()

        config_data = {}
        config_data['notes_check'] = self.toggle_notes_menuitem.IsChecked()
        config_data['notes'] = self.notes_panel.Save()
        config_data['datasets'] = list(self.datasets.keys())
        config_data['options'] = self.options_dict
        config_data['samples'] = list(self.samples.keys())
        config_data['model_iter'] = self.model_iter
        config_data['codes'] = True
        config_data['collection_module'] = self.collection_module.Save()
        config_data['filtering_module'] = self.filtering_module.Save()
        config_data['sampling_module'] = self.sampling_module.Save()
        config_data['coding_module'] = self.coding_module.Save()
        #config_data['reviewing_module'] = self.reviewing_module.Save()
        config_data['reporting_module'] = self.reporting_module.Save()

        self.save_thread = MainThreads.SaveThread(self, Constants.AUTOSAVE_PATH, self.current_workspace.name, config_data, self.datasets, self.samples, self.codes, notes_text, self.last_load_dt, autosave=True)
    
    def OnSaveEnd(self, event):
        logger = logging.getLogger(__name__+".MainFrame.OnSaveEnd")
        logger.info("Starting")
        #once load thread has finished loading data files into memory run the GUI with the loaded data
        if self.autosave_flag == False:
            self.last_load_dt = datetime.now()
        else:
            self.autosave_flag = False
        self.save_thread.join()
        self.save_thread = None
        self.CloseProgressDialog(thaw=True)
        logger.info("Finished")
        if self.closing:
            self.OnCloseEnd(event)

    def OnProgress(self, event):
        self.PulseProgressDialog(event.data)

    def OnCloseStart(self, event):
        '''Menu Function for Closing Application'''
        logger = logging.getLogger(__name__+".MainFrame.OnCloseStart")
        logger.info("Starting")

        self.CreateProgressDialog(title=GUIText.SHUTDOWN_BUSY_LABEL,
                                  freeze=True)
        cancel_flag = False
        if self.multiprocessing_inprogress_flag:
            confirm_dialog = wx.MessageDialog(self, GUIText.MULTIPROCESSING_CLOSING_MSG,
                                              GUIText.CONFIRM_REQUEST, wx.ICON_QUESTION | wx.OK | wx.CANCEL)
            confirm_dialog.SetOKLabel(GUIText.PROCEED)
            if confirm_dialog.ShowModal() == wx.ID_CANCEL:
                cancel_flag = True

        if not cancel_flag:
            check_flag = False
            #check if current workspace is not recently saved
            if not check_flag and len(self.datasets) != 0:
                for key in self.datasets:
                    if self.datasets[key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if not check_flag and len(self.samples) != 0:
                for key in self.samples:
                    if self.samples[key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if not check_flag and len(self.codes) != 0:
                for key in self.codes:
                    if self.codes[key].last_changed_dt > self.last_load_dt:
                        check_flag = True
            if check_flag:
                confirm_dialog = wx.MessageDialog(self, GUIText.CLOSE_WARNING,
                                              GUIText.CONFIRM_REQUEST, wx.ICON_QUESTION | wx.YES_NO | wx.CANCEL)
                confirm_dialog.SetYesNoLabels(GUIText.SAVE, GUIText.SKIP)
                exit_flag = confirm_dialog.ShowModal()
            else:
                exit_flag = wx.ID_NO

            if exit_flag == wx.ID_YES:
                self.closing = True
                self.PulseProgressDialog(text=GUIText.SAVE_BUSY_LABEL)
                self.OnSaveStart(None)
            elif exit_flag == wx.ID_NO:
                self.OnCloseEnd(event)
            else:
                self.CloseProgressDialog(GUIText.CANCELED, thaw=True)
        else:
            self.CloseProgressDialog(GUIText.CANCELED, thaw=True)

        logger.info("Finished")

    def OnCloseEnd(self, event):
        logger = logging.getLogger(__name__+".MainFrame.OnCloseEnd")
        logger.info("Starting")

        #reset objects
        for key in self.codes:
            self.codes[key].DestroyObject()
        self.codes.clear()
        for key in self.samples:
            self.samples[key].DestroyObject()
        self.samples.clear()
        for key in self.datasets:
            self.datasets[key].DestroyObject()
        self.datasets.clear()

        #update gui based on reset objects to prevent errors
        self.DatasetsUpdated(autosave=False)
        self.SamplesUpdated()
        self.DocumentsUpdated(self)
        self.CodesUpdated()

        self.PulseProgressDialog(GUIText.SHUTDOWN_BUSY_POOL)
        logger.info("Starting to shut down of process pool")
        self.pool.close()
        self.pool.join()
        logger.info("Finished shutting down process pool")

        self.CloseProgressDialog(thaw=True, close=True)
        logger.info("Finished")

        windows = wx.GetTopLevelWindows()
        for window in windows:
            window.Destroy()

    #Functions called by other modules
    def CreateProgressDialog(self, title, warning="", freeze=False):
        if freeze:
            self.Freeze()
            self.Disable()
        if self.progress_dialog_references == 0:
            self.progress_dialog = CustomProgressDialog(parent=self,
                                                        title=title,
                                                        warning=warning)
            self.progress_dialog.Show()
        self.progress_dialog_references += 1
    
    def PulseProgressDialog(self, text=""):
        if self.progress_dialog is not None:
            self.progress_dialog.Pulse(text)
    
    def CloseProgressDialog(self, message=GUIText.FINISHED, thaw=False, close=False):
        if self.progress_dialog is not None:
            self.progress_dialog_references -= 1
            if self.progress_dialog_references == 0:
                self.progress_dialog.EndPulse("\n"+message)
                if close:
                    self.progress_dialog.Close()
        if thaw:
            self.Enable()
            self.Thaw()

    def DatasetsUpdated(self, autosave=True):
        logger = logging.getLogger(__name__+".MainFrame.DatasetsUpdated")
        logger.info("Starting")
        self.collection_module.DatasetsUpdated()
        self.filtering_module.DatasetsUpdated()
        self.sampling_module.DatasetsUpdated()
        self.coding_module.DatasetsUpdated()

        if autosave:
            self.AutoSaveStart()
        logger.info("Finished")

    def DocumentsUpdated(self, source):
        logger = logging.getLogger(__name__+".MainFrame.DocumentsUpdated")
        logger.info("Starting")
        for key in self.document_dialogs:
            if source != self.document_dialogs[key].document_panel:
                self.document_dialogs[key].RefreshDetails()
        self.sampling_module.DocumentsUpdated()
        self.coding_module.DocumentsUpdated(source)
        logger.info("Finished")

    def SamplesUpdated(self):
        logger = logging.getLogger(__name__+".MainFrame.SamplesUpdated")
        logger.info("Starting")
        self.sampling_module.SamplesUpdated()
        self.coding_module.DocumentsUpdated(self)
        logger.info("Finished")
    
    def CodesUpdated(self):
        logger = logging.getLogger(__name__+".MainFrame.CodesUpdated")
        logger.info("Starting")
        for key in self.document_dialogs:
            self.document_dialogs[key].RefreshDetails()
        for key in self.codeconnections_dialogs:
            self.codeconnections_dialogs[key].RefreshDetails()
        self.coding_module.CodesUpdated()
        #self.reviewing_module.CodesUpdated()
        self.reporting_module.CodesUpdated()
        logger.info("Finished")

    def ModeChange(self):
        self.collection_module.ModeChange()
        self.sampling_module.ModeChange()
        self.coding_module.DocumentsUpdated(self)
        #self.reviewing_module.ModeChange()
        self.reporting_module.ModeChange()

class CustomProgressDialog(wx.Dialog):
    def __init__(self, parent, title, warning=""):
        wx.Dialog.__init__(self, parent, title=title, style=wx.CAPTION|wx.RESIZE_BORDER)
       
        #h_sizer = wx.BoxSizer(wx.HORIZONTAL)
        v_sizer = wx.BoxSizer(wx.VERTICAL)

        if warning != "":
            warning_text = wx.StaticText(self, label=warning)
            v_sizer.Add(warning_text, 0, wx.EXPAND|wx.ALL, 5)

        self.gauge = wx.Gauge(self)
        v_sizer.Add(self.gauge, 0, wx.EXPAND|wx.ALL, 5)

        self.timer = wx.Timer(self)
        self.start_time = datetime.now()
        elapsed_time = self.start_time - self.start_time
        self.Bind(wx.EVT_TIMER, self.OnUpdateTime, self.timer)
        self.timer_label = wx.StaticText(self, label=str(elapsed_time).split('.')[0])
        v_sizer.Add(self.timer_label, 0, wx.EXPAND|wx.ALL, 5)
        self.timer.Start(1000)

        self.text = wx.TextCtrl(self, -1, GUIText.STARTING+"\n", size=(320,240), style=wx.TE_MULTILINE | wx.TE_READONLY)
        v_sizer.Add(self.text, 1, wx.EXPAND|wx.ALL, 5)

        controls_sizer = self.CreateButtonSizer(wx.OK)
        self.ok_button = wx.FindWindowById(wx.ID_OK, self)
        self.ok_button.SetLabel(GUIText.FINISHED)
        self.ok_button.Disable()
        v_sizer.Add(controls_sizer, 0, wx.ALIGN_RIGHT|wx.ALL, 5)

        self.SetSizerAndFit (v_sizer)
    
    def OnUpdateTime(self, event):
        current_time = datetime.now()
        elapsed_time = current_time - self.start_time
        self.timer_label.SetLabel(str(elapsed_time).split('.')[0])

    def Pulse(self, text):
        self.text.AppendText("\n"+text)
        self.gauge.Pulse()
    
    def EndPulse(self, text):
        self.timer.Stop()
        self.text.AppendText("\n"+text)
        self.gauge.SetValue(self.gauge.GetRange())
        current_time = datetime.now()
        elapsed_time = current_time - self.start_time
        self.timer_label.SetLabel(str(elapsed_time).split('.')[0])
        self.ok_button.Enable()

class OptionsDialog(wx.Dialog):
    def __init__(self, parent, size=Constants.OPTIONS_DIALOG_SIZE):
        wx.Dialog.__init__(self, parent, title=GUIText.OPTIONS_LABEL, size=size, style=wx.DEFAULT_DIALOG_STYLE)

        main_frame = wx.GetApp().GetTopWindow()
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        advanced_sizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=GUIText.OPTIONS_ADVANCED_MODES)
        sizer.Add(advanced_sizer, 0, wx.ALL, 5)

        self.multipledatasets_ctrl = wx.CheckBox(self, label=GUIText.OPTIONS_MULTIPLEDATASETS)
        self.multipledatasets_ctrl.SetValue(main_frame.options_dict['multipledatasets_mode'])
        self.multipledatasets_ctrl.Bind(wx.EVT_CHECKBOX, self.ChangeMultipleDatasetMode)
        advanced_sizer.Add(self.multipledatasets_ctrl, 0, wx.ALL, 5)

        self.adjustable_label_fields_ctrl = wx.CheckBox(self, label=GUIText.OPTIONS_ADJUSTABLE_LABEL_FIELDS)
        self.adjustable_label_fields_ctrl.SetValue(main_frame.options_dict['adjustable_label_fields_mode'])
        self.adjustable_label_fields_ctrl.Bind(wx.EVT_CHECKBOX, self.ChangeAdjustableLabelFieldsMode)
        advanced_sizer.Add(self.adjustable_label_fields_ctrl, 0, wx.ALL, 5)

        self.adjustable_computation_fields_ctrl = wx.CheckBox(self, label=GUIText.OPTIONS_ADJUSTABLE_COMPUTATIONAL_FIELDS)
        self.adjustable_computation_fields_ctrl.SetValue(main_frame.options_dict['adjustable_computation_fields_mode'])
        self.adjustable_computation_fields_ctrl.Bind(wx.EVT_CHECKBOX, self.ChangeAdjustableComputationalFieldsMode)
        advanced_sizer.Add(self.adjustable_computation_fields_ctrl, 0, wx.ALL, 5)

        twitter_sizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=GUIText.TWITTER_LABEL+" "+GUIText.OPTIONS_LABEL)
        sizer.Add(twitter_sizer, 0, wx.EXPAND | wx.ALL, 5)

        twitter_consumer_key_label = wx.StaticText(self, label=GUIText.CONSUMER_KEY + ": ")
        self.twitter_consumer_key_ctrl = wx.TextCtrl(self)
        if 'twitter_consumer_key' in main_frame.options_dict:
            self.twitter_consumer_key_ctrl.SetValue(main_frame.options_dict['twitter_consumer_key'])
        self.adjustable_computation_fields_ctrl.Bind(wx.EVT_TEXT_ENTER, self.ChangeTwitterFields)
        twitter_consumer_key_sizer = wx.BoxSizer(wx.HORIZONTAL)
        twitter_consumer_key_sizer.Add(twitter_consumer_key_label)
        twitter_consumer_key_sizer.Add(self.twitter_consumer_key_ctrl, wx.EXPAND)
        twitter_sizer.Add(twitter_consumer_key_sizer, 0, wx.EXPAND | wx.ALL, 5)
    
        twitter_consumer_secret_label = wx.StaticText(self, label=GUIText.CONSUMER_SECRET + ": ")
        self.twitter_consumer_secret_ctrl = wx.TextCtrl(self)
        if 'twitter_consumer_secret' in main_frame.options_dict:
            self.twitter_consumer_secret_ctrl.SetValue(main_frame.options_dict['twitter_consumer_secret'])
        self.adjustable_computation_fields_ctrl.Bind(wx.EVT_TEXT_ENTER, self.ChangeTwitterFields)
        twitter_consumer_secret_sizer = wx.BoxSizer(wx.HORIZONTAL)
        twitter_consumer_secret_sizer.Add(twitter_consumer_secret_label)
        twitter_consumer_secret_sizer.Add(self.twitter_consumer_secret_ctrl, wx.EXPAND)
        twitter_sizer.Add(twitter_consumer_secret_sizer, 0, wx.EXPAND | wx.ALL, 5)

    def ChangeMultipleDatasetMode(self, event):
        main_frame = wx.GetApp().GetTopWindow()
        new_mode = self.multipledatasets_ctrl.GetValue()
        if main_frame.options_dict['multipledatasets_mode'] != new_mode:
            main_frame.options_dict['multipledatasets_mode'] = new_mode
            main_frame.ModeChange()
        
    def ChangeAdjustableLabelFieldsMode(self, event):
        main_frame = wx.GetApp().GetTopWindow()
        new_mode = self.adjustable_label_fields_ctrl.GetValue()
        if main_frame.options_dict['adjustable_label_fields_mode'] != new_mode:
            main_frame.options_dict['adjustable_label_fields_mode'] = new_mode
            main_frame.ModeChange()
    
    def ChangeAdjustableComputationalFieldsMode(self, event):
        main_frame = wx.GetApp().GetTopWindow()
        new_mode = self.adjustable_computation_fields_ctrl.GetValue()
        if main_frame.options_dict['adjustable_computation_fields_mode'] != new_mode:
            main_frame.options_dict['adjustable_computation_fields_mode'] = new_mode
            main_frame.ModeChange()
    
    def ChangeTwitterFields(self, event):
        main_frame = wx.GetApp().GetTopWindow()
        main_frame.options_dict['twitter_consumer_key'] = self.twitter_consumer_key_ctrl.GetValue()
        main_frame.options_dict['twitter_consumer_secret'] = self.twitter_consumer_secret_ctrl.GetValue()
        if main_frame.options_dict['twitter_consumer_key'] != "" and main_frame.options_dict['twitter_consumer_secret'] != "":
            main_frame.options_dict['twitter_enabled'] = True
        else:
            if 'twitter_allowed' in main_frame.options_dict:
                del main_frame.options_dict['twitter_enabled']

class AboutDialog(wx.Dialog):
    def __init__(self, parent):
        wx.Dialog.__init__(self, parent, title=GUIText.ABOUT, style=wx.DEFAULT_DIALOG_STYLE)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.AddStretchSpacer()

        name_text = wx.StaticText(self, label=GUIText.APP_NAME)
        name_font = name_text.GetFont()
        name_font.MakeBold()
        name_font.MakeLarger()
        name_text.SetFont(name_font)
        sizer.Add(name_text, 0, wx.CENTER)
        sizer.AddSpacer(10)

        version_text = wx.StaticText(self, label=GUIText.ABOUT_VERSION + Constants.CUR_VER)
        sizer.Add(version_text, 0, wx.CENTRE)
        sizer.AddSpacer(5)

        osf_url = HyperlinkCtrl(self, label=GUIText.ABOUT_OSF, url=GUIText.ABOUT_OSF_URL)
        sizer.Add(osf_url, 0, wx.CENTRE)
        sizer.AddSpacer(5)

        github_url = HyperlinkCtrl(self, label=GUIText.ABOUT_GITHUB, url=GUIText.ABOUT_GITHUB_URL)
        sizer.Add(github_url, 0, wx.CENTRE)
        sizer.AddSpacer(5)

        sizer.AddStretchSpacer()
        self.SetSizer(sizer)
        self.Layout()

        

def Main():
    '''setup the main tasks for the application'''
    log_path = os.path.join(Constants.LOG_PATH, "MachineThematicAnalysis.log")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_path, maxBytes=200000, backupCount=200)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    cpus = psutil.cpu_count(logical=False)
    if cpus is None or cpus < 2:
        pool_num = 1
    else:
        pool_num = cpus-1
    with multiprocessing.get_context("spawn").Pool(processes=pool_num) as pool:
        #start up the GUI
        app = RootApp.RootApp()
        MainFrame(None, -1, GUIText.APP_NAME+" - "+GUIText.UNSAVED,
                  style=wx.DEFAULT_FRAME_STYLE, pool=pool)
        #start up the main loop
        app.MainLoop()

if __name__ == '__main__': 
    multiprocessing.freeze_support()
    Main()

    