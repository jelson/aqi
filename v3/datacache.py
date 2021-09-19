# Caching class that accepts records without blocking, and periodically flushes
# the cache to the downstream data sink.

from mylogging import say
import httpclient
import threading
import time
import util

class DataCache(threading.Thread):
    def __init__(self, args):
        threading.Thread.__init__(self)
        self.args = args
        self.daemon = True
        self.cache = []
        self.client = httpclient.DataClient(args)
        self.lock = threading.Lock()
        self.start()

    def append(self, record):
        with self.lock:
            self.cache.append(record)
        if self.args.verbose:
            say(f"got record: {record}")

    def run(self):
        to_xmit = []
        while True:
            # Move any records in the cache into a local variable to transmit to
            # the server
            with self.lock:
                to_xmit.extend(self.cache)
                self.cache.clear()

            # If there is anything to transmit, try to send them to the server
            if len(to_xmit) > 0:
                # Try to send the locally stored records to the server
                retval = self.client.insert_batch(to_xmit)

                # If the send was successful, discard these records. Otherwise, save
                # them so we can try to send them again next time around.
                if retval:
                    to_xmit.clear()

            # Wait until it's time to transmit again
            time.sleep(15)
