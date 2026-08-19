#!/usr/bin/env python
import requests
import rclpy
from rclpy.node import Node
import time

class Tracker(Node):
    def __init__(self):
        super().__init__("public_ip")
        
        timer_period = 300  # seconds
        self.timer = self.create_timer(timer_period, self.publish_data)

    def getIP(self):
        try:
            res = requests.get("http://ipinfo.io/ip").content.decode()
            print("IP address obtained: {}".format(res))
            return res
        except:
            return None

    def publish_data(self):
        try:
            external_ip = self.getIP()
            if external_ip != None:
                r = requests.post('http://therevproject.com/tracking/public_ip.php', 
                    # 'http://localhost:8888', 
                        headers = {'Content-type': 'application/json', 'Accept': 'text/plain', 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36'},
                        json = {
                        'ip' : external_ip,
                        'timestamp' : int(time.time()),
                        'api_key' : 'b9d56841f5e3f09b71beafe833199f8e68df8f7ae34b8f8574b44ce138b9d3a4'
                })
                print("Successfully POSTed to server.")
            else:
                print("Couldn't obtain IP address")
        except:
            print("Couldn't POST to server.")
            pass
        
def main(args=None):
    rclpy.init()
    node = Tracker()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()