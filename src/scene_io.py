import os
import glob
import scipy.io
import numpy as num

__all__ = ['Gamma', 'Matlab', 'ISCE', 'GMTSAR']


class SceneIO(object):
    """ Prototype class for SARIO objects """
    def __init__(self, scene=None):
        if scene is not None:
            self._log = scene._log.getChild('IO/%s' % self.__class__.__name__)
        else:
            import logging
            self._log = logging.logger('SceneIO/%s' % self.__class__.__name__)

        self.container = {
            'phi': None,  # Look incident angle from vertical in degree
            'theta': None,  # Look orientation angle from east; 0deg East,
                            # 90deg North
            'displacement': None,  # Displacement towards LOS
            'llLon': None,  # Lower left corner latitude
            'llLat': None,  # Lower left corner londgitude
            'dLat': None,  # Pixel delta latitude
            'dLon': None,  # Pixel delta longitude
        }

    def read(self, filename, **kwargs):
        """ Read function of the file format

        :param filename: file to read
        :type filename: string
        :param **kwargs: Keyword arguments
        :type **kwargs: {dict}
        """
        raise NotImplementedError('read not implemented')

    def write(self, filename, **kwargs):
        """ Write method for IO

        :param filename: file to write to
        :type filename: string
        :param **kwargs: Keyword arguments
        :type **kwargs: {dict}
        """
        raise NotImplementedError('write not implemented')

    def validate(self, filename, **kwargs):
        """ Validate file format

        :param filename: file to validate
        :type filename: string
        :returns: Validation
        :rtype: {bool}
        """
        pass
        raise NotImplementedError('validate not implemented')


class Matlab(SceneIO):
    """ Reads Matlab files

    Variable naming conventions within Matlab ``.mat`` container:

        ================== ====================
        Property           Matlab ``.mat`` name
        ================== ====================
        Scene.displacement ``ig_``
        Scene.phi          ``phi``
        Scene.theta        ``theta``
        Scene.frame.x      ``xx``
        Scene.frame.y      ``yy``
        ================== ====================
    """
    def validate(self, filename, **kwargs):
        if filename[-4:] == '.mat':
            return True
        else:
            return False
        try:
            variables = self.io.whosmat(filename)
            if len(variables) > 50:
                return False
            return True
        except ValueError:
            return False

    def read(self, filename, **kwargs):
        import utm

        mat = scipy.io.loadmat(filename)
        for mat_k, v in mat.iteritems():
            for io_k in self.container.iterkeys():
                if io_k in mat_k:
                    self.container[io_k] = mat[mat_k]
                elif 'ig_' in mat_k:
                    self.container['displacement'] = mat[mat_k]
                elif 'xx' in mat_k:
                    utm_e = mat[mat_k].flatten()
                elif 'yy' in mat_k:
                    utm_n = mat[mat_k].flatten()

        if utm_e.min() < 1e4 or utm_n.min() < 1e4:
            utm_e *= 1e3
            utm_n *= 1e3
        utm_zone = 32
        utm_zone_letter = 'N'
        try:
            self.container['llLat'], self.container['llLon'] =\
                utm.to_latlon(utm_e.min(), utm_n.min(),
                              utm_zone, utm_zone_letter)
            urlat, urlon = utm.to_latlon(utm_e.max(), utm_n.max(),
                                         utm_zone, utm_zone_letter)
            self.container['dLat'] =\
                (urlat - self.container['llLat']) /\
                self.container['displacement'].shape[0]

            self.container['dLon'] =\
                (urlon - self.container['llLon']) /\
                self.container['displacement'].shape[1]
        except utm.error.OutOfRangeError:
            self.container['llLat'], self.container['llLon'] = (0., 0.)
            self.container['dLat'] = (utm_e[1] - utm_e[0]) / 110e3
            self.container['dLon'] = (utm_n[1] - utm_n[0]) / 110e3
            self._log.warning('Could not interpret spatial vectors, '
                              'referencing to 0, 0 (lat, lon)')
        return self.container


class Gamma(SceneIO):
    """ Reads in binary files processed with Gamma.

    .. note::

        Data has to be georeferenced to latitude/longitude!

    Expects two files:

        * Binary file from gamma (``*``)
        * Parameter file (``*par``), including ``corner_lat, corner_lon,
            nlines, width, post_lat, post_lon``
    """
    def _getParameterFile(self, path):
        path = os.path.dirname(os.path.realpath(path))
        par_files = glob.glob('%s/*par' % path)

        for file in par_files:
            try:
                self._parseParameterFile(file)
                self._log.debug('Found parameter file %s' % file)
                return file
            except ImportError:
                continue
        raise ImportError('Could not find suiting Gamma parameter file (*par)')

    @staticmethod
    def _parseParameterFile(par_file):
        import re

        params = {}
        required = ['corner_lat', 'corner_lon', 'nlines', 'width',
                    'post_lat', 'post_lon']
        rc = re.compile(r'^(\w*):\s*([a-zA-Z0-9+-.*]*\s[a-zA-Z0-9_]*).*')

        with open(par_file, mode='r') as par:
            for line in par:
                parsed = rc.match(line)
                if parsed is None:
                    continue

                groups = parsed.groups()
                try:
                    params[groups[0]] = float(groups[1])
                except ValueError:
                    params[groups[0]] = groups[1].strip()

        for r in required:
            if r not in params:
                raise ImportError(
                    'Parameter file does not hold required parameter %s' % r)

        return params

    def validate(self, filename, **kwargs):
        try:
            par_file = kwargs.pop('par_file',
                                  self._getParameterFile(filename))
            self._parseParameterFile(par_file)
            return True
        except ImportError:
            return False

    def _getAngle(self, filename, pattern):
        path = os.path.dirname(os.path.realpath(filename))
        phi_files = glob.glob('%s/%s' % (path, pattern))
        if len(phi_files) == 0:
            self._log.warning('Could not find %s file, defaulting to 0.'
                              % pattern)
            return 0.
        elif len(phi_files) > 1:
            self._log.warning('Found multiple %s files, defaulting to 0.'
                              % pattern)
            return 0.

        filename = phi_files[0]
        self._log.debug('Found %s in %s' % (pattern, filename))
        return num.memmap(filename, mode='r', dtype='>f4')

    def read(self, filename, **kwargs):
        """ Reads in Gamma scene

        :param filename: Gamma software binary file
        :type filename: str
        :param par_file: Corresponding parameter (``*par``) file. (optional)
        :type par_file: str
        :returns: Import dictionary
        :rtype: dict
        :raises: ImportError
        """
        par_file = kwargs.pop('par_file',
                              self._getParameterFile(filename))
        par = self._parseParameterFile(par_file)
        fill = None

        try:
            nrows = int(par['width'])
            nlines = int(par['nlines'])
        except:
            raise ImportError('Error parsing width and nlines from %s' %
                              par_file)

        displ = num.fromfile(filename, dtype='>f4')
        # Resize array if last line is not scanned completely
        if (displ.size % nrows) != 0:
            fill = num.empty(nrows - displ.size % nrows)
            fill.fill(num.nan)
            displ = num.append(displ, fill)

        displ = displ.reshape(nlines, nrows)
        displ[displ == -0.] = num.nan

        phi = self._getAngle(filename, '*phi*')
        theta = self._getAngle(filename, '*theta*')
        theta = num.cos(theta)

        if fill is not None:
            theta = num.append(theta, fill)
            phi = num.append(phi, fill)

        theta = theta.reshape(nlines, nrows)
        phi = phi.reshape(nlines, nrows)

        # LatLon UTM Conversion
        self.container['displacement'] = displ*1e-2
        self.container['llLat'] = par['corner_lat'] + par['post_lat'] * nrows
        self.container['llLon'] = par['corner_lon']
        self.container['dLon'] = par['post_lon']
        self.container['dLat'] = par['post_lat']
        self.container['theta'] = theta
        self.container['phi'] = phi
        return self.container


class ISCEXMLParser(object):
    def __init__(self, filename):
        import xml.etree.ElementTree as ET
        self.root = ET.parse(filename).getroot()

    @staticmethod
    def type_convert(value):
        for t in (float, int, str):
            try:
                return t(value)
            except ValueError:
                continue
        raise ValueError('Could not convert value')

    def getProperty(self, name):
        for child in self.root.iter():
            if child.get('name') == name:
                if child.tag == 'property':
                    return self.type_convert(child.find('value').text)
                elif child.tag == 'component':
                    values = {}
                    for prop in child.iter('property'):
                        values[prop.get('name')] =\
                            self.type_convert(prop.find('value').text)
                    return values
        return None


class ISCE(SceneIO):
    """Reads in files processed with ISCE

    Expects three files in the same folder:

        * Unwrapped displacement binary (``*.unw.geo``)
        * Metadata XML (``*.unw.geo.xml``)
        * LOS binary data (``*.rdr.geo``)
    """
    def validate(self, filename, **kwargs):
        try:
            self._getDisplacementFile(filename)
            self._getLOSFile(filename)
            return True
        except ImportError:
            return False

    @staticmethod
    def _getLOSFile(path):
        if not os.path.isdir(path):
            path = os.path.dirname(path)
        rdr_files = glob.glob(os.path.join(path, '*.rdr.geo'))

        if len(rdr_files) == 0:
            raise ImportError('Could not find LOS file (.rdr.geo)')
        return rdr_files[0]

    @staticmethod
    def _getDisplacementFile(path):
        if os.path.isfile(path):
            disp_file = path
        else:
            files = glob.glob(os.path.join(path, '*.unw.geo'))
            if len(files) == 0:
                raise ImportError('Could not find displacement file '
                                  '(.unw.geo) at %s', path)
            disp_file = files[0]

        if not os.path.isfile('%s.xml' % disp_file):
            raise ImportError('Could not find displacement XML file '
                              '(%s.unw.geo.xml)' % os.path.basename(disp_file))
        return disp_file

    def read(self, path, **kwargs):
        path = os.path.abspath(path)
        isce_xml = ISCEXMLParser(self._getDisplacementFile(path) + '.xml')

        coord_lon = isce_xml.getProperty('coordinate1')
        coord_lat = isce_xml.getProperty('coordinate2')
        self.container['dLat'] = num.abs(coord_lat['delta'])
        self.container['dLon'] = num.abs(coord_lon['delta'])
        nlon = int(coord_lon['size'])
        nlat = int(coord_lat['size'])

        self.container['llLat'] = coord_lat['startingvalue'] +\
            (nlat * coord_lat['delta'])
        self.container['llLon'] = coord_lon['startingvalue']

        displacement = num.memmap(self._getDisplacementFile(path),
                                  dtype='<f4')\
            .reshape(nlat, nlon*2)[:, nlon:]
        displacement[displacement == 0.] = num.nan
        self.container['displacement'] = displacement*1e-2

        los_data = num.fromfile(self._getLOSFile(path), dtype='<f4')\
            .reshape(nlat, nlon*2)
        self.container['phi'] = los_data[:, :nlon]
        self.container['theta'] = los_data[:, nlon:] + 90.

        return self.container


class GMTSAR(SceneIO):
    """ Reads in data processed with GMT5SAR

    Use gmt5sar ``SAT_look`` to calculate the corresponding unit look vectors:

    .. code-block:: sh

        gmt grd2xyz unwrap_ll.grd | gmt grdtrack -Gdem.grd |
        awk {'print $1, $2, $4'} |
        SAT_look 20050731.PRM -bos > 20050731.los.enu

    Expects two binary files:

        * Displacement grid (NetCDF, ``*los_ll.grd``)
        * LOS binary data (see instruction, ``*los.enu``)

    """
    def validate(self, filename, **kwargs):
        try:
            if self._getDisplacementFile(filename)[-4:] == '.grd':
                return True
        except ImportError:
            return False
        return False

    def _getLOSFile(self, path):
        if not os.path.isdir(path):
            path = os.path.dirname(path)
        los_files = glob.glob(os.path.join(path, '*.los.*'))
        if len(los_files) == 0:
            self._log.warning(GMTSAR.__doc__)
            raise ImportError('Could not find LOS file (*.los.*)')
        return los_files[0]

    @staticmethod
    def _getDisplacementFile(path):
        if os.path.isfile(path):
            return path
        else:
            files = glob.glob(os.path.join(path, '*.grd'))
            if len(files) == 0:
                raise ImportError('Could not find displacement file '
                                  '(*.grd) at %s', path)
            disp_file = files[0]
        return disp_file

    def read(self, path, **kwargs):
        from scipy.io import netcdf
        path = os.path.abspath(path)

        grd = netcdf.netcdf_file(self._getDisplacementFile(path),
                                 mode='r', version=2)
        self.container['displacement'] = grd.variables['z'][:].copy()
        self.container['displacement'] *= 1e-2
        shape = self.container['displacement'].shape
        # LatLon
        self.container['llLat'] = grd.variables['lat'][:].min()
        self.container['llLon'] = grd.variables['lon'][:].min()

        self.container['dLat'] = (grd.variables['lat'][:].max() -
                                  self.container['llLat'])/shape[1]
        self.container['dLon'] = (grd.variables['lon'][:].max() -
                                  self.container['llLon'])/shape[0]

        # Theta and Phi
        try:
            los = num.memmap(self._getLOSFile(path), dtype='<f4')
            e = los[3::6].copy().reshape(shape)
            n = los[4::6].copy().reshape(shape)
            u = los[5::6].copy().reshape(shape)

            theta = num.rad2deg(num.arctan(n/e))
            phi = num.rad2deg(num.arccos(u))
            theta[n < 0] += 180.

            self.container['phi'] = phi
            self.container['theta'] = theta
        except ImportError:
            self._log.warning('Defaulting theta and phi to 0')
            self.container['theta'] = 0.
            self.container['phi'] = 0.

        return self.container
