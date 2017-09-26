# LIBRARIES
import requests
import pandas as pd
from lxml import html
from . import constants as k
from . import io, classes
import os
import urllib.request
import numpy as np
from tools import constants
from selenium import webdriver
from astropy.table import Table
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

# *** START: PUBLIC METHODS ***

# Catalogues download
def all_transients_catalog(overwrite=False):
    filename = 'all_transients.pickle'
    filepath = k.DIR_CATALOGUES_OBJECTS + filename
    file_exists = os.path.isfile(filepath)
    io.makedir(k.DIR_CATALOGUES_OBJECTS)
    if not file_exists or overwrite:
        all_objects_catalog = pd.DataFrame()
        for object_type in classes.ObjectTypes:
            new_catalog = __object_catalog__(object_type, overwrite)
            new_catalog['Type'] = object_type.value.upper()
            all_objects_catalog = all_objects_catalog.append(new_catalog, ignore_index=True)
        all_objects_catalog.reset_index(drop=True, inplace=True)
        all_objects_catalog.to_pickle(filepath)
        return all_objects_catalog
    else:
        df = pd.read_pickle(filepath)
        return df

def supernovae_catalog(overwrite=False):
    return __object_catalog__(classes.ObjectTypes.supernovae, overwrite)
def cv_catalog(overwrite=False):
    return __object_catalog__(classes.ObjectTypes.cv, overwrite)
def blazars_catalog(overwrite=False):
    return __object_catalog__(classes.ObjectTypes.blazars, overwrite)
def agn_catalog(overwrite=False):
    return __object_catalog__(classes.ObjectTypes.agn, overwrite)

# Light curves download
def all_transients_light_curves(df, overwrite=False):
    all_transients_light_curves = __generate_transient_light_curves__(df, overwrite)
    return all_transients_light_curves

def all_permanents_light_curves(transient_df, overwrite=False):
    all_permanents_light_curves = __generate_permanents_light_curves__(transient_df, overwrite)
    return all_permanents_light_curves

# *** END: PUBLIC METHODS ***

# *** START: OBJECT CATALOGUES HELPER METHODS ***
def __object_catalog__(object_type, overwrite):
    filename = '{}.pickle'.format(object_type.value)
    filepath = k.DIR_CATALOGUES_OBJECTS + filename
    file_exists = os.path.isfile(filepath)
    io.makedir(k.DIR_CATALOGUES_OBJECTS)
    if not file_exists or overwrite:
        df = pd.DataFrame()
        for url in k.OBJECTS_CATALOGUES_URLS[object_type.value]:
            df = df.append(__retrieve_object_catalog__(url, object_type))
        df.to_pickle(filepath)
    else:
        df = pd.read_pickle(filepath)
    return df
    
def __retrieve_object_catalog__(url, object_type):
    ra_list, dec_list = [], []
    date_list, clas_list = [], []
    
    r = requests.get(url)
    tree = html.fromstring(r.content)
    rows = tree.findall('.//tr')[1:]
    
    indexes = k.OBJECTS_CATALOGUES_INDEXES[object_type.value]
    for row in rows:
        vals = row.findall('td')
        if len(vals) < 4:
            continue
        ra = vals[indexes['ra']].text_content().strip(' \t\n\r')
        dec = vals[indexes['dec']].text_content().strip(' \t\n\r')
        date = vals[indexes['date']].text_content().strip(' \t\n\r')
        clas = vals[indexes['clas']].text_content().strip(' \t\n\r')

        ra_list.append(ra); dec_list.append(dec)
        date_list.append(date); clas_list.append(clas)

    data = {'ra' : ra_list, 'dec' : dec_list, 'date' : date_list, 'clas' : clas_list}
    return pd.DataFrame(data)
# *** END: OBJECT CATALOGUES HELPER METHODS ***

#  *** START: LIGHT CURVES HELPER METHODS ***
def __init_driver__():
    driver = webdriver.Chrome()
    driver.set_window_size(700, 1800) 
#    driver.implicitly_wait() # seconds
    driver.set_page_load_timeout(600)
    return driver
        
def __raw_light_curves_url__(query_file_path, driver):
    query_file_path = os.path.abspath(query_file_path)
    driver.find_element_by_css_selector('input[name="DB"][value="orphancat"]').click()
    driver.find_element_by_css_selector('input[name="upload_file"]').send_keys(query_file_path)
    driver.find_element_by_css_selector('input[type="submit"]').send_keys("\n")
    submit_button = driver.find_elements(By.XPATH, '//input[@type="submit"]')
    if len(submit_button):            
        submit_button[0].click()
        txtCaptchaDiv = driver.find_element_by_css_selector('span[id="txtCaptchaDiv"]')
        txtInput = driver.find_element_by_css_selector('input[name="txtInput"]')
        print('Captcha Text', txtCaptchaDiv.text)
        txtInput.send_keys(txtCaptchaDiv.text)
        driver.find_element_by_css_selector('button[type="submit"]').click()
    view_button = driver.find_element_by_css_selector('input[type="button"]')
    url = view_button.get_attribute('onclick').split('=')[1][1:-1]
    return url

def __retrieve_light_curves__(query_file_path, filename, outdir):
    url = 'http://nesssi.cacr.caltech.edu/cgi-bin/getmulticonedb_release2.cgi'
    driver = __init_driver__()
    driver.get(url)
    url = __raw_light_curves_url__(query_file_path, driver)
    driver.quit()
    
    if url:
        raw_light_curves_path = __download_file__(url, filename, outdir, overwrite=True)
        return raw_light_curves_path
    else:
        return None
    
def __create_query_file__(obj_catalog_df, start_index, end_index):
    query_file_path = './query_file.txt'
    with open(query_file_path, 'w+') as file:
        for i, row in obj_catalog_df[start_index:end_index].iterrows():
            index = i
            ra = row['ra']
            dec = row['dec']
            file.write('{} {} {}\n'.format(i, ra, dec))
    return query_file_path

def __format_raw_light_curves__(raw_light_curves_df):
    raw_light_curves_df.rename(columns={'InputID':'ObjectID'}, inplace=True)
    
def __generate_transient_light_curves__(obj_catalog_df, overwrite):
    outdir = k.DIR_CATALOGUES_LIGHTCURVES_GROUPED
    filename = 'all_transients_light_curves.pickle'
    filepath = outdir + filename
    io.makedir(outdir)
    if io.file_exists(filename, outdir, verbose=False) and not overwrite:
        return pd.read_pickle(filepath)
    else:
        temp_light_curves_catalogues_out_dir = outdir + 'temp/transients/'
        io.makedir(temp_light_curves_catalogues_out_dir)
        light_curves_df = pd.DataFrame()
        step, n_rows = 100, obj_catalog_df.shape[0]
        for i in range(0, n_rows, step):
            existing_light_curves_filename = 'part{}.tbl'.format(int(i/step))
            light_curves_table_path = temp_light_curves_catalogues_out_dir + existing_light_curves_filename
            if not io.file_exists(existing_light_curves_filename, temp_light_curves_catalogues_out_dir, verbose=False):
                query_file_path = __create_query_file__(obj_catalog_df, i, i+step)
                light_curves_table_path = __retrieve_light_curves__(query_file_path, existing_light_curves_filename, temp_light_curves_catalogues_out_dir)
                if not light_curves_table_path: print('Error in seq. {}, curves not found'.format(i))
            raw_light_curves_df = Table.read(light_curves_table_path, format='ascii').to_pandas()
            __format_raw_light_curves__(raw_light_curves_df)
            light_curves_df = light_curves_df.append(raw_light_curves_df, ignore_index=True)
        light_curves_df.to_pickle(filepath)
        return light_curves_df

#  *** END: LIGHT CURVES HELPER METHODS ***

def __download_file__(url, name, outdir, overwrite=False):
    if not os.path.exists(outdir):
        os.makedirs(outdir)
    filepath = outdir + name
    file_exists = os.path.isfile(filepath)
    if file_exists and not overwrite:
        print('File {} already exists'.format(name))
        pass
    else:        
        print('Downloading {}'.format(filepath))
        urllib.request.urlretrieve(url, filepath)
    return filepath