import logging
import os
import cPickle
import time

from ansible.plugins.lookup import aws_secret
from cryptography.fernet import Fernet, InvalidToken

__metaclass__ = type


DOCUMENTATION = aws_secret.DOCUMENTATION
RETURN = aws_secret.RETURN


class LookupModule(aws_secret.LookupModule):
    """
    Adds commcare-cloud specific caching to aws_secret lookup plugin for big speedup

    To cache even between forks of the same process/run, we use a one-time process-wide key
    to encrypt values and write them to disk in files <env_dir>/.generated/.
    After the run is over, the encryption key is lost to time and the files are useless
    and indecipherable even by the person who ran it.
    """
    def run(self, terms, variables, **kwargs):
        terms = tuple(terms)
        term, = terms
        value = self.get_cache(term, inventory_dir=variables['inventory_dir'])
        try:
            if value is Ellipsis:
                logging.debug('Fetching secret {}'.format(terms))
                try:
                    value = super(LookupModule, self).run(terms, variables, **kwargs)
                except Exception as e:
                    logging.debug('Caching error fetching secret: {}'.format(e))
                    value = e
                self.set_cache(term, value, inventory_dir=variables['inventory_dir'])
        except Exception as e:
            logging.warn('There was an error fetching or caching the secret: {}'.format(e))
            raise

        if isinstance(value, Exception):
            raise value
        else:
            return value

    def get_cache(self, term, inventory_dir):
        try:
            with open(self._secrets_cache_filename(term, inventory_dir=inventory_dir), 'rb') as f:
                contents = f.read()
                if contents == b'FETCHING':
                    time.sleep(1)
                    return self.get_cache(term, inventory_dir=inventory_dir)
                return cPickle.loads(Fernet(self._encryption_key()).decrypt(contents))
        except (IOError, InvalidToken, cPickle.UnpicklingError):
            with open(self._secrets_cache_filename(term, inventory_dir=inventory_dir), 'wb') as f:
                f.write(b'FETCHING')
            return Ellipsis

    def set_cache(self, term, value, inventory_dir):
        try:
            with open(self._secrets_cache_filename(term, inventory_dir=inventory_dir), 'wb') as f:
                f.write(Fernet(self._encryption_key()).encrypt(cPickle.dumps(value)))
        except Exception as e:
            logging.warn('There was an error caching the secret {}'.format(e))
            raise

    def _encryption_key(self):
        return os.environ['AWS_SECRETS_CACHE_KEY']

    def _secrets_cache_filename(self, term, inventory_dir):
        dir_name = os.path.join(inventory_dir, '.generated')
        if not os.path.isdir(dir_name):
            os.mkdir(dir_name)

        return os.path.join(dir_name, 'secrets_cache_{}'.format(hash(term)))
