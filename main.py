from time import sleep

from kivy.app import App
from kivy.app import Builder
from kivy.properties import StringProperty
from kivy.properties import ObjectProperty
from kivy.properties import BooleanProperty
from kivy.properties import NumericProperty
from kivy.uix.button import Button
from kivy.event import EventDispatcher
from kivy.logger import Logger
from kivy.clock import Clock, mainthread
from kivy.config import ConfigParser
from kivy.network.urlrequest import UrlRequest
from kivy.uix.screenmanager import ScreenManager, Screen
# Phidget specific imports
from Phidgets.PhidgetException import PhidgetErrorCodes, PhidgetException
from Phidgets.Events.Events import AttachEventArgs, DetachEventArgs, ErrorEventArgs, OutputChangeEventArgs, TagEventArgs
from Phidgets.Devices.RFID import RFID, RFIDTagProtocol
from Phidgets.Phidget import PhidgetLogLevel

from kivy.properties import NumericProperty
from kivy.lang import Builder

Builder.load_string('''
#:import random random.random
#:import SlideTransition kivy.uix.screenmanager.SlideTransition
#:import SwapTransition kivy.uix.screenmanager.SwapTransition
#:import WipeTransition kivy.uix.screenmanager.WipeTransition
#:import FadeTransition kivy.uix.screenmanager.FadeTransition
#:import RiseInTransition kivy.uix.screenmanager.RiseInTransition
#:import FallOutTransition kivy.uix.screenmanager.FallOutTransition
#:import NoTransition kivy.uix.screenmanager.NoTransition

<CustomScreen>:
    hue: random()
    current_user: root.current_user
    canvas:
        Color:
            hsv: self.hue, .5, .3
        Rectangle:
            size: self.size

    Label:
        font_size: 42
        text: root.name

    Button:
        text: 'Next screen'
        size_hint: None, None
        pos_hint: {'right': 1}
        size: 150, 50
        on_release: root.manager.current = root.manager.next()

    Button:
        text: 'Previous screen'
        size_hint: None, None
        size: 150, 50
        on_release: root.manager.current = root.manager.previous()

''')


class CustomScreen(Screen):
    hue = NumericProperty(0)
    tag = StringProperty(force_dispatch=True)

    def on_tag(self, instance, value):
        Logger.warning("Screen got a new RFID tag: {}".format(value))


class UserManager(EventDispatcher):
    ''' Manage users on the Monitor '''

    # todo: do something based on the current screen, maybe stop a timer? e.g. hold screen

    tag_gained = ObjectProperty(force_dispatch=True)    # rfid tag id e.g., 023af7dd
    current_user = StringProperty()  # tag id of currently logged in user.
    waiting_for_logon = BooleanProperty()
    waiting_for_logoff = BooleanProperty()
    request_error = BooleanProperty()
    employee = ObjectProperty()

    def __init__(self):
        super(UserManager, self).__init__()
        self.waiting_for_logoff = False
        self.waiting_for_logon = False
        self.current_user = ''
        self.request_error = False
        self.employee = None
        # self.employee = Employee()
        self.app = ObjectProperty()

    def on_tag_gained(self, instance, value):
        valid_card = self.validate_card(value)
        if valid_card is False:
            Logger.warn('User Manager: someone attempted to access the system with an invalid card.')
        else:
            Logger.info('User Manager: the tag [{}] was valid.'.format(value))
            # self.app.root.current_screen.tag = value
            self.app.last_gained_tag = self.employee

    def validate_card(self, rfid_tag):
        Logger.info('User Manager: validate_card with rfid_tag: {}'.format(rfid_tag))

        self.app = App.get_running_app()

        headers = {
            'Accept': 'application/json',
            'Content-type': 'application/json',
            'Cache-Control': 'no-cache',
            'Authorization': 'Token ' + self.app.config.get('Software', 'license key')
        }

        req = UrlRequest('http://{}/api/1.0/employees/?format=json&rfid_tag={}'.format(
            self.app.config.get('Network', 'server fqdn'), rfid_tag),
            on_success=self.url_request_on_success,
            on_error=self.url_request_on_error,
            on_failure=self.url_request_on_failure,
            req_headers=headers)

        # don't use wait, but maximum 10s timeout
        for i in range(50):
            Clock.tick()
            sleep(.5)
            if req.is_finished:
                break

        # A valid tag will have an 'id' key in its data.
        if 'id' in self.employee:
            return True     # valid API response from server
        else:
            self.employee = []
            return False    # invalid API response sent by server

    def url_request_on_success(self, *args):
        Logger.info('User Manager: url_request_on_success')
        self.request_error = False
        if args[1]['count'] is 1:
            self.employee = args[1]['results'][0]  # get the guts of the result (i.e., the employee record)
        else:
            self.employee = []
            Logger.debug('User Manager: Invalid response from server: {}'.format(args[1]))

    def url_request_on_error(self, *args):
        self.request_error = True
        Logger.warning('User Manager: url_request_on_error')
        for arg in args:
            print repr(arg)

    def url_request_on_failure(self, *args):
        Logger.warning('User Manager: url_request_on_error')
        self.request_error = True
        for arg in args:
            print repr(arg)


class Reader:
    ''' Phidgets 125khz RFID Reader/Writer '''

    def __init__(self):
        # Create an RFID object
        try:
            self.rfid = RFID()
            self.user_manager = UserManager()
        except RuntimeError as e:
            Logger.info("RFID: Phidget Runtime Exception: %s" % e.details)
            Logger.info("RFID: Phidget Exiting....")
            exit(1)

        #Main Phiget Program Code
        try:
                #logging example, uncomment to generate a log file
            #rfid.enableLogging(PhidgetLogLevel.PHIDGET_LOG_VERBOSE, "phidgetlog.log")

            self.rfid.setOnAttachHandler(self.rfidAttached)
            self.rfid.setOnDetachHandler(self.rfidDetached)
            self.rfid.setOnErrorhandler(self.rfidError)
            self.rfid.setOnOutputChangeHandler(self.rfidOutputChanged)
            self.rfid.setOnTagHandler(self.rfidTagGained)
            self.rfid.setOnTagLostHandler(self.rfidTagLost)
        except PhidgetException as e:
            Logger.exception("RFID: Phidget Exception %i: %s" % (e.code, e.details))
            Logger.exception("RFID: Exiting....")
            exit(1)

        Logger.info("RFID: Opening phidget object....")

        try:
            self.rfid.openPhidget()
        except PhidgetException as e:
            Logger.info("RFID: Phidget Exception %i: %s" % (e.code, e.details))
            Logger.info("RFID: Exiting....")
            exit(1)

        Logger.info("RFID: Waiting for attach....")

        try:
            self.rfid.waitForAttach(10000)
        except PhidgetException as e:
            Logger.exception("RFID: Phidget Exception %i: %s" % (e.code, e.details))
            try:
                self.rfid.closePhidget()
            except PhidgetException as e:
                Logger.exception("RFID: Phidget Exception %i: %s" % (e.code, e.details))
                Logger.exception("RFID: Exiting....")
                exit(1)
            Logger.exception("RFID: Exiting....")
            exit(1)
        else:
            self.displayDeviceInfo()

        Logger.info("RFID: Turning on the RFID antenna....")
        self.rfid.setAntennaOn(True)

    # Information Display Function
    def displayDeviceInfo(self):
        Logger.info("RFID: |------------|----------------------------------|--------------|------------|")
        Logger.info("RFID: |- Attached -|-              Type              -|- Serial No. -|-  Version -|")
        Logger.info("RFID: |------------|----------------------------------|--------------|------------|")
        Logger.info("RFID: |- %8s -|- %30s -|- %10d -|- %8d -|" % (self.rfid.isAttached(), self.rfid.getDeviceName(),
                                                                   self.rfid.getSerialNum(), self.rfid.getDeviceVersion()))
        Logger.info("RFID: |------------|----------------------------------|--------------|------------|")
        Logger.info("RFID: Number of outputs: %i -- Antenna Status: %s -- Onboard LED Status: %s" %
                    (self.rfid.getOutputCount(), self.rfid.getAntennaOn(), self.rfid.getLEDOn()))

    #Event Handler Callback Functions
    def rfidAttached(self, e):
        self.attached = e.device
        Logger.info("RFID: %i Attached!" % (self.attached.getSerialNum()))

    def rfidDetached(self, e):
        self.detached = e.device
        Logger.info("RFID: %i Detached!" % (self.detached.getSerialNum()))

    def rfidError(self, e):
        try:
            source = e.device
            Logger.exception("RFID: %i Phidget Error %i: %s" % (self.source.getSerialNum(), e.eCode, e.description))
        except PhidgetException as e:
            Logger.exception(("RFID: Phidget Exception %i: %s" % (e.code, e.details)))

    def rfidOutputChanged(self, e):
        self.source = e.device
        Logger.info("RFID: %i Output %i State: %s" % (self.source.getSerialNum(), e.index, e.state))

    def rfidTagGained(self, e):
        self.rfid.setLEDOn(1)
        Logger.info("RFID: Tag gained: {}".format(e.tag))
        self.user_manager.tag_gained = e.tag   # this sets up the UserManager.on_tag_gained() to be called

    def rfidTagLost(self, e):
        self.rfid.setLEDOn(0)
        Logger.info("RFID: Tag lost: {}".format(e.tag))


class PhidgetApp(App):

    use_kivy_settings = False
    last_gained_tag = ObjectProperty(force_dispatch=True)

    # start the RFID Reader thread
    rfid = Reader()

    def __init__(self, *args, **kwargs):
        super(PhidgetApp, self).__init__(*args, **kwargs)
        self.config = ConfigParser()

    def build(self):
        config = self.config.read('phidget.ini')
        self.title = 'Phidget RFID Test'
        root = ScreenManager()
        for x in range(3):
            root.add_widget(CustomScreen(name='Screen %d' % x))
        return root

    def on_last_gained_tag(self, instance, value):
        Logger.info('Last Gained Tag: {}'.format(value['employee_type']))
        if 1 in value["employee_type"]:   # Operator
            self.root.current = 'Screen 0'
        if 2 in value["employee_type"]:   # Supervisor
            self.root.current = 'Screen 1'
        if 3 in value["employee_type"]:   # Supervisor
            self.root.current = 'Screen 2'
        self.root.current_screen.tag = value["rfid_tag"]


if __name__ == '__main__':
    PhidgetApp().run()


'''
{
    u'phone_number': u'',
    u'employee_status': [1],
    u'sms_email_address': u'sms email goes here',
    u'notes': u'1st Shift Operator',
    u'rfid_tag': u'023af76c',
    u'employee_type': [1],
    u'email_address': u'email needed for notifications',
    u'id': 12
}
'''