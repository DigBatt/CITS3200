#!/usr/bin/env python

import os
import requests
import math
from std_msgs.msg import String, Float32
from gps_msgs.msg import GPSFix
import rclpy
from rclpy.node import Node
import time
from gps_msgs.msg import GPSFix

class Tracker(Node):
    def __init__(self):
        super().__init__("gps_tracker")
            
        self.create_subscription(GPSFix, "/gps", self.gps_fix_callback, 10)
        self.create_subscription(Float32, "/battery_percent", self.battery_callback, 10)

        self.latitude = None
        self.longitude = None
        self.heading = None

        self.lastTime = time.time()

        self.batteryPercentage = None

        self.bus_id = os.environ.get('HOSTNAME')[-1]
        if (not self.bus_id.isnumeric()) or (self.bus_id is None):
            self.get_logger().error(f"Could not get bus ID")
            rclpy.shutdown()
        
        self.get_logger().info("Initialised")
        self.get_logger().info(f"Bus ID {self.bus_id}")

    def battery_callback(self, data):
        try:
            percentage = data.data #float(data.data.split(' | ')[3].split('State of Charge: ')[1])
        except:
            return

        self.batteryPercentage = percentage

    def gps_fix_callback(self, data):
        # if data.status.position_valid:
        self.latitude = data.latitude
        self.longitude = data.longitude
        # else:
        #     self.get_logger().info("position not valid")
        
        # self.get_logger().info(f"lat: {self.latitude}, lon: {self.longitude}")

        now = time.time()
        if now - self.lastTime > 5:
            self.publish_data()
            self.lastTime = now

    def heading_callback(self, data):
        # Convert to East=0, anticlockwise = positive (from North=0, clockwise=positive)
        # self.heading = -math.degrees(data.angle.z) + 90.0
        pass

    def publish_data(self):
        request_body = {
            'timestamp': int(time.time()),
            'api_key': 'b9d56841f5e3f09b71beafe833199f8e68df8f7ae34b8f8574b44ce138b9d3a4'
        }

        if self.latitude is not None and self.longitude is not None:
            request_body['lat'] = self.latitude
            request_body['lon'] = self.longitude

        if self.heading is not None:
            request_body['heading'] = self.heading

        if self.batteryPercentage is not None:
            request_body['battery'] = self.batteryPercentage

        try:
            if self.bus_id == 1:
                url = f'https://therevproject.com/tracking/gps_pos.php'
            else:
                url = f'https://therevproject.com/tracking/gps_pos{self.bus_id}.php'
                
            r = requests.post(url,
                              headers={'Content-type': 'application/json', 'Accept': 'text/plain',
                                       'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) '
                                                     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 '
                                                     'Safari/537.36'},
                              json=request_body,
                              verify=False)
            if r.status_code == 200:
                self.get_logger().info("Successfully POSTed to server.")
            else:
                self.get_logger().warn("Status code" + str(r.status_code))
        except Exception as e:
            self.get_logger().warn("Couldn't POST to server. " + str(e))
            pass


def main(args=None):
    rclpy.init()
    node = Tracker()
    rclpy.spin(node)
    rclpy.shutdown()


if __name__ == '__main__':
    main()