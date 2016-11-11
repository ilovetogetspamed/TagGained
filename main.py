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

# Phidget specific imports
from Phidgets.PhidgetException import PhidgetErrorCodes, PhidgetException
from Phidgets.Events.Events import AttachEventArgs, DetachEventArgs, ErrorEventArgs, OutputChangeEventArgs, TagEventArgs
from Phidgets.Devices.RFID import RFID, RFIDTagProtocol
from Phidgets.Phidget import PhidgetLogLevel


# class UserManager(EventDispatcher):
#
#     tag_gained = ObjectProperty()
#     current_user = StringProperty()
#
#     def __init__(self):
#         super(UserManager, self).__init__()
#
#     def on_tag_gained(self, instance, value):
#         if self.current_user == '':
#             self.current_user = value  # value being the tag gained?
#             Logger.info 'did it work?  I got {}'.format(self.current_user)
#         else:
#             Logger.info 'New tag gained {}'.format(value)4


class UserManager(EventDispatcher):
    ''' Manage users on the Monitor '''

    # todo: do something based on the current screen, maybe stop a timer? e.g. hold screen

    tag_gained = ObjectProperty()    # rfid tag id e.g., 023af7dd
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
            Logger.debug('User Manager: Invalid response from server: s{}'.format(args[1]))

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

    # start the RFID Reader thread
    rfid = Reader()

    def __init__(self, *args, **kwargs):
        super(PhidgetApp, self).__init__(*args, **kwargs)
        self.config = ConfigParser()

    def callback(self, instance):
        Logger.info('The button <%s> is being pressed' % instance.text)

    def build(self):
        config = self.config.read('phidget.ini')
        self.title = 'Hello world'
        btn1 = Button(text='Push Me')
        btn1.bind(on_press=self.callback)
        return btn1

if __name__ == '__main__':
    PhidgetApp().run()