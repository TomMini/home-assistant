""" TomMotica X10 Lights  """
import logging
from threading import Thread
import requests
import voluptuous as vol

# Import the device class from the component that you want to support
from homeassistant.components.light import (Light, ATTR_BRIGHTNESS, ATTR_TRANSITION,
                                            PLATFORM_SCHEMA, SUPPORT_BRIGHTNESS,
                                            SUPPORT_TRANSITION)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD

import homeassistant.helpers.config_validation as cv

from signalr import Connection

# Home Assistant depends on 3rd party packages for API specific code.
REQUIREMENTS = ['signalr-client==0.0.7']

_LOGGER = logging.getLogger(__name__)

SUPPORT_TOMMOTICA_LIGHT = (SUPPORT_BRIGHTNESS | SUPPORT_TRANSITION)
SUPPORT_TOMMOTICA_APPLIANCE = 0
DOMAIN = "light"
PLATFORM_NAME = "tommotica"

# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_PORT, default=8998): cv.port,
    vol.Optional(CONF_USERNAME, default='admin'): cv.string,
    vol.Optional(CONF_PASSWORD): cv.string,
})

def setup_platform(hass, config, add_devices, discovery_info=None):
    """ Setup the TomMotica Light platform. """
    # Assign configuration variables.  The configuration check takes care they
    # are present.
    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT)
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    url = 'http://{0}:{1}'.format(host, port)

    service = TomMoticaService(hass, url)
    service.start()

    # Add devices
    add_devices(service.lights)

class TomMoticaService:
    """ Service that connects with the TomMotica Service """
    _lights = []
    _url = ''

    def __init__(self, hass, url):
        self._url = url
        self._hass = hass
        background_thread = Thread(target=self.monitor)
        background_thread.daemon = True
        background_thread.start()

    def start(self):
        """ Start the Service TODO: embed background_thread and only start once """
        response = requests.get(self._url + '/api/house?api-version=2')
        data = response.json()
        for floor in data['Floors']:
            for room in floor['Rooms']:
                for appliance in room['Appliances']:
                    print('Appliance: ', appliance)
                    self._lights.append(TomMoticaAppliance(appliance, self._url))

    @property
    def lights(self):
        """ Get the Lights that are discovered """
        return self._lights

    def monitor(self):
        """ Monitor running in Background """
        with requests.Session() as session:
            connection = Connection(self._url + '/signalr', session)
            hub = connection.register_hub('applianceHub')

            print('SignalR starting')
            connection.start()
            print('SignalR started')

            #create error handler
            def print_error(error):
                """ Print errors """
                print('SignalR error: ', error)

            hub.client.on('updated', self.device_update)

            #process errors
            connection.error += print_error
            with connection:
                while True:
                    connection.wait()

    def device_update(self, updated):
        """ Update eventhandler from SignalR """
        for light in self._lights:
            if updated['Id'] == light.tommotica_id:
                light.update_state(updated['State'])

class TomMoticaAppliance(Light):
    """Representation of a TomMotica Appliance/Light."""

    def __init__(self, appliance, base_url):
        self._appliance = appliance
        self._dimable = 'DimLevel' in appliance["State"]
        self._url = '{}/api/appliance/{}/State?api-version=2'.format(base_url, appliance['Id'])

    @property
    def unique_id(self) -> str:
        return 'tommotica_' + self._appliance['Id']

    @property
    def tommotica_id(self) -> str:
        """ TomMotica Id """
        return self._appliance['Id']

    @property
    def name(self) -> str:
        """Return the display name of this light."""
        return self._appliance['Name']

    @property
    def brightness(self):
        """Brightness of the light (an integer in the range 1-255)."""
        if self._dimable:
            return int(float(self._appliance['State']['DimLevel']) * 255 / 100)

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._appliance['State']['On'] is True

    @property
    def supported_features(self):
        """Flag supported features."""
        if self._dimable:
            return SUPPORT_TOMMOTICA_LIGHT
        return SUPPORT_TOMMOTICA_APPLIANCE

    def update_state(self, newstate):
        """If the new state is defferent, change it"""
        if self.states_differ(self._appliance['State'], newstate):
            self._appliance['State'] = newstate
            self.schedule_update_ha_state()

    def states_differ(self, state1, state2) -> bool:
        """See if the states are any different"""
        if state1['On'] != state2['On']:
            return True
        if self._dimable and state1['DimLevel'] != state2['DimLevel']:
            return True
        return False

    def turn_on(self, **kwargs):
        """Instruct the light to turn on.

        You can skip the brightness part if your light does not support
        brightness control.
        """

        newstate = self._appliance['State']
        newstate['On'] = True

        if self._dimable:
            if ATTR_TRANSITION in kwargs:
                newstate['TransitionTime'] = kwargs[ATTR_TRANSITION]
            if ATTR_BRIGHTNESS in kwargs:
                newstate['DimLevel'] = int(float(kwargs.get(ATTR_BRIGHTNESS, 255)) * 100 / 255)

        response = requests.put(self._url, json=newstate)
        data = response.json()
        self._appliance['State'] = data

    def turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        #self._state = False
        newstate = self._appliance['State']
        newstate['On'] = False
        response = requests.put(self._url, json=newstate)
        data = response.json()
        self._appliance['State'] = data

    def update(self):
        """Fetch new state data for this light.

        This is the only method that should fetch new data for Home Assistant.
        """
