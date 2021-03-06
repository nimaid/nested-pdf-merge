#!/usr/bin/env python3

import argparse, os, sys
from pathlib import Path
import re
import atexit

# Test if this is a PyInstaller executable or a .py file
if getattr(sys, 'frozen', False):
    IS_EXE = True
    PROG_FILE = sys.executable
    PROG_PATH = os.path.dirname(PROG_FILE) 
    PATH = sys._MEIPASS
else:
    IS_EXE = False
    PROG_FILE = os.path.realpath(__file__)
    PROG_PATH = os.path.dirname(PROG_FILE)
    PATH = PROG_PATH

PROG_FILE_NAME = os.path.splitext(os.path.basename(PROG_FILE))[0]

# Get path that the command was called from
COMMAND_PATH = Path().absolute()

# Setup exit handler (used for cleanup)
job_complete = None
exit_funcs = list()
def exit_handler():
    global job_complete
    if len(exit_funcs) > 0:
        print()
        print("-------- CLEANUP --------")
        for f in exit_funcs:
            f()
    if job_complete != None: # defined at the very end only
        job_complete()
atexit.register(exit_handler)

# Parse arguments before running main program
def dir_path(string):
    if os.path.isdir(string):
        return string
    else:
        raise NotADirectoryError(string)

#TODO: Add usage examples
ap = argparse.ArgumentParser(description="Merge nested image directory into PDF with nested bookmarks.")
ap.add_argument("-i", "--input_dir", type=dir_path, required=True,
    help="path to nested image directory to merge")
ap.add_argument("-o", "--output_file", type=str, default=None,
    help="output file path ( defaults to [input_dir].pdf )")
ap.add_argument("-s", "--order_number_separator", type=str, default=None,
    help="the character used to separate the directory ordering numbers from the bookmark names ( like '.' or ')' )")
ap.add_argument("-n", "--no_pdf", action="store_true",
    help="just scan directory and print table of contents")
ap.add_argument("-p", "--purify", action="store", default=None, nargs="*", type=str, 
    help="purify scanned B&W page ( greyscale, sharpen, threshold ), named sub-arguments: (sharpen|s) (threshold|t)")
ap.add_argument("-d", "--dpi", type=int, default=None,
    help="dots-per-inch of the input images")
ap.add_argument("-t", "--title", type=str, default=None,
    help="the PDF title ( defaults to the directory basename )")
ap.add_argument("-a", "--author", type=str, default=None,
    help="the PDF author")
ap.add_argument("-f", "--table_of_contents_format", action="store", default=None, nargs="*", type=str, 
    help="formatting options for the table of contents, named sub-arguments: (break_limit|b) (number_prefix|p) (number_postfix|a) (indent|i)")
args = vars(ap.parse_args())

print()

# Resolve input dir into absolute path (relative to working directory!)
input_dir = args["input_dir"]
input_dir = os.path.realpath(input_dir)
if not os.path.isabs(input_dir):
    input_dir_split = input_dir.split(os.path.sep)
    if input_dir_split[0] == os.path.curdir:
        input_dir = os.path.sep.join(input_dir_split[1:])
    input_dir = os.path.join(COMMAND_PATH, input_dir)

input_dir_name = input_dir.strip(os.path.sep).split(os.path.sep)[-1]

# Get main directory
main_dir = os.path.sep.join(input_dir.rstrip(os.path.sep).split(os.path.sep)[:-1])

# Test if/which purify flavor is being used
if args["purify"] != None:
    purify = True
    purify_args = args["purify"]
else:
    purify = False
    purify_args = ()

# Do not purify if --no_pdf is set
if args["no_pdf"]:
    purify = False

# Parse purify sub-arguments (values)
if purify:
    # Defaults
    sharpen_factor = 2
    thresh_setting = 170
    
    for p_arg in purify_args:
        p_arg_split = p_arg.split("=")
        
        # Only allow [string]=[string]
        if len(p_arg_split) != 2:
            raise argparse.ArgumentTypeError("Invalid argument format. Use arg_name=arg_value.")

        # Get name and value separately
        p_arg_name, p_arg_value = [x.lower().strip() for x in p_arg_split]

        # Parse purify named sub-arguments
        if p_arg_name in ["sharpen", "s"]:
            # Test if it's a float and set
            worked = True
            try:
                sharpen_factor = float(p_arg_value)
            except(ValueError):
                worked = False
            
            # Test if it's greater than 0
            if sharpen_factor <= 0:
                worked = False
            
            if not worked:
                raise argparse.ArgumentTypeError("(--purify | -p) sharpness must be a float greater than 0.")
        elif p_arg_name in ["threshold", "t"]:
            # Test if it's a float and set
            worked = True
            try:
                thresh_setting = float(p_arg_value)
            except(ValueError):
                worked = False
            
            # Test if it's positive
            if thresh_setting < 0:
                worked = False
            
            # Test if it's <= 255
            if thresh_setting > 255:
                worked = False
            
            if not worked:
                raise argparse.ArgumentTypeError("(--purify | -p) threshold must be a positive float <= 255.")
        else:
            raise argparse.ArgumentTypeError("'{}' is not a valid option for (--purify | -p).".format(p_arg_name))

# Fuction to read the first line in a text file
def read_string_from_file(string_file_name):
    with open(string_file_name, 'r', encoding='utf-8') as f:
        result = f.read()
    return result.strip().split("\n")[0].strip()

# Function to make any string into a valid filename
def get_valid_filename(s):
    s = str(s).strip()
    return re.sub(r'(?u)[\/\\\:\*\?\"\<\>\|]', '_', s)

# Function to turn a path into the name after the os.path.extsep (even if no name)
def path_to_ext(path_in):
    path_in_path, path_in_filename = os.path.split(path_in)
    path_in_basename, path_in_ext = os.path.splitext(path_in_filename)
    path_in_ext = path_in_ext.lower()
    if path_in_ext == "":
        # No name, just extention
        path_in_ext = path_in_basename
    if len(path_in_ext) <= 0:
        # Must be a directory
        return None
    elif path_in_ext[0] != ".":
        # No actual extention
        return ""
    else:
        return path_in_ext

# Set file extentions to ignore
ignored_file_exts = [".ignore", ".db"]

# Set valid image extentions
page_exts = [".jpg", ".jpeg", ".png", ".gif"]

# Set rename extentions
rename_exts = [".name", ".title"]

# Set author extentions
author_exts = [".author"]

# Set DPI extentions
dpi_exts = [".dpi"]

# Set blank page extentions
blank_exts = [".blank"]
page_exts += blank_exts

metadata_file_exts = rename_exts + author_exts + dpi_exts
valid_exts = ignored_file_exts + page_exts + metadata_file_exts + blank_exts

# Get files in main input directory
input_dir_files = [str(p) for p in Path(input_dir).glob("*") if os.path.isfile(p)]

# Set/limit DPI
dpi_files = [p for p in input_dir_files if path_to_ext(p) in dpi_exts]
if len(dpi_files) > 1:
    raise argparse.ArgumentTypeError("Multiple DPI files found in the main directory! Please use at most 1.")
if args["dpi"] != None:
    pdf_dpi = args["dpi"]
    if len(dpi_files) > 0:
        print("[WARNING]: A DPI file exists in the main directory, but the --dpi argument overrides this.")
elif len(dpi_files) > 0:
    try:
        pdf_dpi = int(read_string_from_file(dpi_files[0]))
    except ValueError:
        argparse.ArgumentTypeError("DPI setting from DPI file must be a valid integer.")
else:
    pdf_dpi = int(300)
if (pdf_dpi < 72) or (pdf_dpi > 4800):
    raise argparse.ArgumentTypeError("DPI must be 72 <= DPI <= 4800. Current setting: '{}'".format(pdf_dpi))

# Set PDF title
title_files = [p for p in input_dir_files if path_to_ext(p) in rename_exts]
if len(title_files) > 1:
    raise argparse.ArgumentTypeError("Multiple title/name files found in the main directory! Please use at most 1.")
use_pdf_title = True
if args["title"] != None:
    if len(title_files) > 0:
        print("[WARNING]: A title/name file exists in the main directory, but the --title argument overrides this.")
    pdf_title = args["title"]
elif len(title_files) > 0:
    pdf_title = read_string_from_file(title_files[0])
else:
    pdf_title = input_dir_name
    use_pdf_title = False

# Set PDF author
author_files = [p for p in input_dir_files if path_to_ext(p) in author_exts]
if len(author_files) > 1:
    raise argparse.ArgumentTypeError("Multiple author files found in the main directory! Please use at most 1.")
if args["author"] != None:
    if len(author_files) > 0:
        print("[WARNING]: An author file exists in the main directory, but the --author argument overrides this.")
    pdf_author = args["author"].strip()
elif len(author_files) > 0:
    pdf_author = read_string_from_file(author_files[0])
else:
    pdf_author = ""

# Resolve output filename
if not args["no_pdf"]:
    if args["output_file"] == None:
        # Default to title
        pdf_title_safe_filename = get_valid_filename(pdf_title)
        output_file = os.path.join(main_dir, pdf_title_safe_filename) + os.path.extsep + "pdf"
    else:
        out_dir, out_name = os.path.split(args["output_file"])
        out_name_split = out_name.split(os.path.extsep)
        if len(out_name_split) >= 2:
            # There is an extension
            output_file = args["output_file"]
            if out_name_split[-1].lower() != "pdf":
                output_file += os.path.extsep + "pdf"
        else:
            # No extension provided
            output_file = args["output_file"] + os.path.extsep + "pdf"
    
    output_file = os.path.realpath(output_file)  
    output_file_dir, output_file_name = os.path.split(output_file)

# Test if special ToC formatting is used
if args["table_of_contents_format"] != None:
    tocf_args = args["table_of_contents_format"]
else:
    tocf_args = ()

# Defaults
toc_line_break_limit = None
pagenum_pre = "Page #"
pagenum_post = "  "
ident_str = "--- "

# Parse ToC formatting sub arguments
for tocf_arg in tocf_args:
    tocf_arg_split = tocf_arg.split("=")
    
    # Only allow [string]=[string]
    if len(tocf_arg_split) != 2:
        raise argparse.ArgumentTypeError("Invalid argument format. Use arg_name=arg_value.")
    
    # Get name and value separately
    tocf_arg_name, tocf_arg_value = [x.lower() for x in tocf_arg_split]
    
    # Parse ToC formatting named sub-arguments
    if tocf_arg_name in ["break_limit", "b"]:
        # Test if it's an int and set
        worked = True
        try:
            toc_line_break_limit = int(tocf_arg_value.strip())
        except(ValueError):
            worked = False
        
        # Test if it's greater than min_toc_line_break_limit
        min_toc_line_break_limit = 10
        if toc_line_break_limit == 0:
            toc_line_break_limit = None
            workied=True
        elif toc_line_break_limit <= min_toc_line_break_limit:
            worked = False
        
        if not worked:
            raise argparse.ArgumentTypeError("(--break_limit | -b) length must be an integer greater than {}, or 0 for no limit.".format(min_toc_line_break_limit))
    elif tocf_arg_name in ["number_prefix", "p"]:
        pagenum_pre = tocf_arg_value
    elif tocf_arg_name in ["number_postfix", "a"]:
        pagenum_post = tocf_arg_value
    elif tocf_arg_name in ["indent", "i"]:
        ident_str = tocf_arg_value
    else:
        raise argparse.ArgumentTypeError("'{}' is not a valid option for (--break_limit | -b).".format(tocf_arg_name))

# Parse purify sub-arguments (values)
if purify:
    # Defaults
    sharpen_factor = 2
    thresh_setting = 170
    
    for p_arg in purify_args:
        p_arg_split = p_arg.split("=")
        
        # Only allow [string]=[string]
        if len(p_arg_split) != 2:
            raise argparse.ArgumentTypeError("Invalid argument format. Use arg_name=arg_value.")

        # Get name and value separately
        p_arg_name, p_arg_value = [x.lower().strip() for x in p_arg_split]

        # Parse purify named sub-arguments
        if p_arg_name in ["sharpen", "s"]:
            # Test if it's a float and set
            worked = True
            try:
                sharpen_factor = float(p_arg_value)
            except(ValueError):
                worked = False
            
            # Test if it's greater than 0
            if sharpen_factor <= 0:
                worked = False
            
            if not worked:
                raise argparse.ArgumentTypeError("(--purify | -p) sharpness must be a float greater than 0.")
        elif p_arg_name in ["threshold", "t"]:
            # Test if it's a float and set
            worked = True
            try:
                thresh_setting = float(p_arg_value)
            except(ValueError):
                worked = False
            
            # Test if it's positive
            if thresh_setting < 0:
                worked = False
            
            # Test if it's <= 255
            if thresh_setting > 255:
                worked = False
            
            if not worked:
                raise argparse.ArgumentTypeError("(--purify | -p) threshold must be a positive float <= 255.")
        else:
            raise argparse.ArgumentTypeError("'{}' is not a valid option for (--purify | -p).".format(p_arg_name))



# Print main program warnings
if args["no_pdf"] and args["purify"] != None:
    print("[WARNING]: Both (--purify|-p) and (--no_pdf|-n) arguments were passed, will not make PDF.")

# Print settings
print()
print("-------- PDF SETTINGS --------")
pdf_no_title_string = "PDF will have no title."
if use_pdf_title:
    if len(pdf_title) <= 0:
        print(pdf_no_title_string)
    else:
        print("PDF title: {}".format(pdf_title))
else:
    print(pdf_no_title_string)

if len(pdf_author) <= 0:
    print("PDF will have no author.")
else:
    print("PDF author: {}".format(pdf_author))

if not args["no_pdf"]:
    print("PDF resolution: {} DPI".format(pdf_dpi))

print("Input directory: {}".format(input_dir))

if args["no_pdf"]:
    print("Will only print the Table of Contents, will NOT process images or save PDF.")
else:
    # Print target filename
    print("Output filename: {}".format(output_file))

if purify:
    print("Will purify documents:")
    print("\tSharpening factor: {}".format(sharpen_factor))
    print("\tThreshold: {}.".format(thresh_setting))

if args["table_of_contents_format"] != None:
    print("Table of Contents formatting:")
    print("\tName length break limit: {}".format(toc_line_break_limit))
    print("\tPage number prefix: '{}'".format(pagenum_pre))
    print("\tPage number postfix: '{}'".format(pagenum_post))
    print("\tIndent text: '{}'".format(ident_str))


# We will be catching KeyboardInterrupts
try:
    # Do main imports
    import img2pdf
    from PIL import Image, ImageEnhance
    from collections import OrderedDict
    from PyPDF2 import PdfFileWriter, PdfFileReader
    import shutil
    import textwrap

    print()
    print("-------- DIRECTORY SCANNING --------")
    print("Scanning directory: '{}'...".format(input_dir))

    # Walk though folder structure (recursive alphabetical, include all files/folders)
    input_dir_list = [str(p) for p in sorted(Path(input_dir).glob('**/*'))]

    # Prefix to prepend to temporary file/folder names
    temp_name_prepend = "__temp__"

    # The temporary directory name
    temp_dir_name = temp_name_prepend + input_dir_name
    temp_dir = os.path.join(main_dir, temp_dir_name)
    
    if not args["no_pdf"]:
        # Delete temp dir if it exists
        def clean_temp_dir():
            if os.path.exists(temp_dir):
                if os.path.isdir(temp_dir):
                    shutil.rmtree(temp_dir)
                elif os.path.isfile(temp_dir):
                    os.remove(temp_dir)
        clean_temp_dir()
        
        # Make temp directory
        os.mkdir(temp_dir)
        
        # Set up exit function to clean up if exited early
        def exit_clean_temp_dir():
            print("Delete temporary directory: {}".format(temp_dir))
            clean_temp_dir()
            print("\tDone!")
        exit_funcs.append(exit_clean_temp_dir)
    
    # Make final input dir names
    if purify:
        # Temp directory
        final_input_dir = temp_dir
    else:
        # The original directory
        final_input_dir = input_dir

    # Save image paths (and empty/ignored-file dirs) paths to ordered list
    page_list = list()
    # Make dict with rename (dir, bm_name)
    page_dir_rename_dict = dict()
    for p in input_dir_list:
        if os.path.isfile(p):
            # Check if it's an invalid extention, and if so, fully ignore it
            p_ext = path_to_ext(p)
            
            if p_ext not in valid_exts:
                print("[UNSUPPORTED]: {}".format(p))
                continue
            
            # Test if it's a metadata file, and if so, fully ignore
            if p_ext in metadata_file_exts:
                continue
            
            # Test if it should be ignored, and if so, fully ignore it
            if p_ext in ignored_file_exts:
                print("[IGNORING]: {}".format(p))
                continue
            
            # Test if the path length is nearing the Windows limit
            windows_path_limit = 260
            unix_path_limit = 4096
            wiggle_room = 40
            p_path_length = len(p)
            min_path_length = min(windows_path_limit, unix_path_limit)
            if p_path_length > min_path_length - wiggle_room:
                print("[WARNING] Dangerously long pathname: {}".format(p))
                print("\tPath length: {} characters".format(p_path_length))
                print("\tWindows maximum path length: {} characters".format(windows_path_limit))
                print("\tUnix maximum path length: {} characters".format(unix_path_limit))
                print("\tRenaming, moving, or downloading this folder may cause errors unless you shorten the names of the file/folders.")
                print("\Recommended action: Use '.name' files (instead of the folder names) to define bookmark names.")
                
            page_list.append(p)
        elif os.path.isdir(p):
            # Get files and directories inside p
            p_list = [os.path.realpath(str(x)) for x in sorted(Path(p).glob('*'))]
            p_dir_list = [x for x in p_list if os.path.isdir(x)]
            p_file_list = [x for x in p_list if os.path.isfile(x)]
            
            # Make file list without ignored files
            p_file_list_ignored = list()
            # Also update page_dir_rename_dict
            for x in p_file_list:
                x_path, x_filename = os.path.split(x)
                x_ext = path_to_ext(x)

                # Check if it's a valid extention
                if x_ext in valid_exts:
                    # If not ignored file, append to file list
                    if x_ext not in ignored_file_exts + metadata_file_exts:
                        p_file_list_ignored.append(x)
                    # If it's a rename file, parse and append to rename dict
                    if x_ext in rename_exts:
                        # If purify, make sure it's referencing the final input dir
                        if purify:
                            relative_x_path = os.path.relpath(x_path, input_dir)
                            rename_dir = os.path.join(final_input_dir, relative_x_path)
                        else:
                            rename_dir = x_path

                        rename_name = read_string_from_file(x)
                        
                        page_dir_rename_dict[rename_dir] = rename_name
            
            # Test if it's empty or contains only ignored files
            if len(p_dir_list) <= 0 and len(p_file_list_ignored) <= 0:
                # Add path (used to make "empty" bookmarks)
                page_list.append(p)
    print("\tDone scanning directory!")

    # Get number of pages
    num_pages = len([p for p in page_list if os.path.isfile(p)])
    num_image_pages = len([p for p in page_list if os.path.isfile(p) and os.path.splitext(p)[-1] not in blank_exts])
    num_pages_len = len(str(num_pages))
    num_image_pages_len = len(str(num_image_pages))
    print("\tPage count: {}".format(num_pages))

    # Run purification (save to temporary directory)
    if purify and num_image_pages > 0:
        print()
        print("-------- PURIFICATION --------")
        print("Saving purified images to temporary directory: {}".format(final_input_dir))
        
        # Delete temp dir (or file with same name) if it already exists
        clean_temp_dir()
        
        # Create new page_list
        new_page_list = list()
        new_page_list_dirs = list()
        new_page_list_files = list()
        for p in page_list:
            # Make final_p (replace input_dir with final_input_dir)
            rel_p = os.path.relpath(p, input_dir)
            final_p = os.path.join(final_input_dir, rel_p)
            new_page_list.append(final_p)
            if os.path.isdir(p):
                new_page_list_dirs.append(final_p)
            else:
                new_page_list_files.append(final_p)
        
        # Make all directories first
        for p in new_page_list_dirs:
            Path(p).mkdir(parents=True, exist_ok=True)
        for p in new_page_list_files:
            Path(os.path.dirname(p)).mkdir(parents=True, exist_ok=True)
        
        # Process image files
        curr_page = 0 # Will go to 1 before first print
        for x, p in enumerate(page_list):
            final_p = new_page_list[x]
            if os.path.isfile(p):
                # It's a page file
                if os.path.splitext(p)[-1] in blank_exts:
                    # It's a blank page file, just copy
                    shutil.copy(p, final_p)
                else:
                    # It's an image file, process
                    curr_page += 1
                    with Image.open(p) as page_im:
                        if purify:
                            curr_page_str = str(curr_page).rjust(num_image_pages_len)
                            print("[PURIFY] ({}/{}): {}".format(curr_page_str, num_image_pages, p))
                            # Make greyscale
                            gray = page_im.convert('L')
                            
                            # Sharpen 
                            enhancer = ImageEnhance.Sharpness(gray)
                            sharpen = enhancer.enhance(sharpen_factor)
                            
                            # Apply threshold
                            thresh = sharpen.point(lambda p: p > thresh_setting and 255)  
                            
                            # Make 1 bit
                            final_page_im = thresh.convert('1')
                        else:
                            final_page_im = page_im
                    
                    # Save image
                    final_page_im.save(final_p, "PNG", dpi=(pdf_dpi, pdf_dpi))
                
        # Update page_list with new images/paths
        page_list = new_page_list
        
        print("\tDone purifying images!")
    
    # Get size from first image
    pl_files_images = [p for p in page_list if os.path.isfile(p) and os.path.splitext(p)[-1] not in blank_exts]
    if num_image_pages > 0:
        with Image.open(pl_files_images[0]) as cover:
            width, height = cover.size
    else:
        width = int(pdf_dpi * 8.5) # Assume 8.5in
        height = int(pdf_dpi * 11) # Assume 11in
    
    # Get number of blank pages
    num_blank_pages = num_pages - num_image_pages
    
    # Test if blank pages are used
    if num_blank_pages > 0:
        blanks_used = True
    else:
        blanks_used = False
    
    if blanks_used and not args["no_pdf"]:
        print()
        print("-------- BLANK PAGES --------")
        print("Saving blank page images to temporary directory: {}".format(final_input_dir))
    
        # Make pure white images for .blank files
        #TODO: Figure out how to make truly blank pages (or at least smaller file sizes)
        new_page_list = list()
        blank_page_num = 0 # Goes to 1 on first page
        for p in page_list:
            page_basename = os.path.relpath(p, input_dir)
            page_temp = os.path.realpath(os.path.join(temp_dir, page_basename))
            
            if os.path.isfile(p):
                if os.path.splitext(p)[-1] in blank_exts:
                    blank_page_num += 1
                    
                    # Make a white PNG in the temporary folder
                    blank_page_name = os.path.splitext(page_basename)[0] + ".png"
                    blank_page_filename = os.path.realpath(os.path.join(temp_dir, blank_page_name))
                    
                    curr_page_str = str(blank_page_num).rjust(len(str(num_blank_pages)))
                    print("[BLANK] ({}/{}): {}".format(curr_page_str, num_blank_pages, blank_page_filename))
                    blank_page = Image.new('1', (width, height), color = "white")
                    
                    Path(os.path.dirname(blank_page_filename)).mkdir(parents=True, exist_ok=True)
                    blank_page.save(blank_page_filename, "PNG", dpi=(pdf_dpi, pdf_dpi))
                    new_page_list.append(blank_page_filename)
                else:
                    # Copy image to temp (fix extra bookmark due to relative directory error)
                    if p != page_temp:
                        Path(os.path.dirname(page_temp)).mkdir(parents=True, exist_ok=True)
                        shutil.copy(p, page_temp)
                    new_page_list.append(page_temp)
            else:
                # Make directory in temp (fixes error mentioned above)
                Path(page_temp).mkdir(parents=True, exist_ok=True)
                new_page_list.append(page_temp)
        page_list = new_page_list
        
        print("\tDone creating blank pages!")
    
    # Make page_list but with only files
    page_list_files = [p for p in page_list if os.path.isfile(p)]

    # Create nested ordered dictionary from list
    page_dict = OrderedDict()
    for p in page_list:
        p = os.path.relpath(p, final_input_dir) # Make relative
        
        current_level = page_dict
        for part in p.split(os.path.sep):
            if part not in current_level:
                current_level[part] = OrderedDict()
            current_level = current_level[part]



    # Create PDF from page_list(no bookmarks)
    if not args["no_pdf"]:
        print()
        print("-------- PDF CREATION --------")
        temp_pdf = os.path.join(output_file_dir, temp_name_prepend + output_file_name)
        print("Creating PDF document from image files...")
        temp_pdf_file_binary = img2pdf.convert(page_list_files, dpi=pdf_dpi, x=None, y=None)
        print("\tDone!")
        
        # Setup exit handler to delete temp PDF
        input_pdf_file = None
        def exit_clean_temp_pdf():
            print("Delete temporary PDF: {}".format(temp_pdf))
            if input_pdf_file != None:
                input_pdf_file.close()
            os.remove(temp_pdf)
            print("\tDone!")
        exit_funcs.append(exit_clean_temp_pdf)
        
        print("Saving temporary PDF: {}".format(temp_pdf))
        with open(temp_pdf, "wb") as f:
            f.write(temp_pdf_file_binary)
        print("\tDone!")
        
        # Load PDF into PyPDF2
        print("Loading temporary PDF into editing library...")
        output_pdf = PdfFileWriter()
        input_pdf_file = open(temp_pdf, 'rb')
        input_pdf = PdfFileReader(input_pdf_file)
        output_pdf.appendPagesFromReader(input_pdf)
        print("\tDone!")
    
    
    print()
    print("-------- BOOKMARKS --------")
    print("Creating bookmark hierarchy from directory structure...")
    # Save ToC lines to list
    #TODO: Save ToC to file option
    toc_dict_list = list()
    if len([p for p in page_dict.values() if p != OrderedDict()]) <= 0:
        print()
        if not args["no_pdf"]:
            print("[WARNING]: No subdirectories found, not creating bookmarks.")
        else:
            print("[ERROR]: No subdirectories found, no table of contents to generate.")
    else:
        # Add nested bookmarks from page_dict
        ident_level = 0
        last_page_index = -1 # Because we want the next page to be 0
        path_list = list()
        bookmark_list = list()
        page_ref = None
        def iterdict(d, base_path="", empty_parents_in=list()):
            global ident_level
            global path_list
            global last_page_index
            global page_ref
            global toc_dict_list

            for k, v in d.items():
                filepath = os.path.join(base_path, os.path.sep.join(path_list))
                filename = os.path.join(filepath, k)
                filename = os.path.realpath(filename)
                
                # Get parent bookmark
                if len(bookmark_list) > 0:
                    bm_parent = bookmark_list[-1]
                else:
                    bm_parent = None
                
                # Get bookmark name
                if filename in page_dir_rename_dict:
                    # Name is defined in a rename file
                    bm_name = page_dir_rename_dict[filename]
                elif args["order_number_separator"] != None:
                    # Remove leading order numbers from dir name
                    k_split = k.split(args["order_number_separator"])
                    if len(k_split) <= 1:
                        bm_name = k
                    else:
                        bm_name = args["order_number_separator"].join(k_split[1:]).strip(" ")
                else:
                    bm_name = k
                
                page_ref = last_page_index + 1
                
                # Test if it's a file or a directory
                if len(v) > 0:
                    # It's a not-fully-empty dir (pages/folders)
                    
                    # Get recursive list of files and folders
                    v_list = [str(x) for x in Path(filename).glob('**/*')]
                    v_dir_list = [x for x in v_list if os.path.isdir(x)]
                    v_file_list = [x for x in v_list if os.path.isfile(x) and os.path.splitext(x)[-1] in page_exts]
                    
                    # Deal with recursively empty folders
                    empty_parents = list()
                    if len(v_file_list) <= 0:
                        # Test if is not a subdir of an empty_parent
                        is_subdir_of_empty_parent = False
                        for empty_parent in empty_parents:
                            if os.path.commonpath([filename, empty_parent]) == empty_parent:
                                is_subdir_of_empty_parent = True
                        if not is_subdir_of_empty_parent:
                            # This is the main parent
                            page_ref += 1
                            empty_parents.append(filename)
                    
                    # Prevent referencing non-existent pages
                    page_ref = min(page_ref, num_pages - 1)
                    
                    # Save to toc_dict_list
                    toc_dict_list.append({
                        "name": bm_name,
                        "level": ident_level,
                        "page": page_ref + 1
                        })
                    
                    ident_level += 1
                    
                    if not args["no_pdf"]:
                        # Add bookmark w/ parent, save as potential parent
                        bm = output_pdf.addBookmark(bm_name, page_ref, parent=bm_parent)
                        
                        # Add to bookmarks list
                        bookmark_list.append(bm)
                    
                    path_list.append(k)
                    
                    # Do recursion
                    iterdict(v, base_path=base_path, empty_parents_in=empty_parents)
                    
                    if not args["no_pdf"]:
                        temp = bookmark_list.pop()
                    temp = path_list.pop()
                    
                    ident_level -= 1
                else:
                    # Either it's a file or an empty (placeholder) dir
                    if os.path.isdir(filename):
                        # It's a totally empty directory, make an "empty" bookmark (no pages/children, references next page)
                        
                        # Deal with children of empty parents
                        empty_parents = empty_parents_in
                        is_subdir_of_empty_parent = False
                        for empty_parent in empty_parents:
                            if os.path.commonpath([filename, empty_parent]) == empty_parent:
                                is_subdir_of_empty_parent = True
                        if is_subdir_of_empty_parent:
                            # Adjust page number forward
                            page_ref += 1
                        
                        # Prevent referencing non-existent pages
                        page_ref = min(page_ref, num_pages - 1)
                        
                        # Save to toc_dict_list
                        toc_dict_list.append({
                            "name": bm_name,
                            "level": ident_level,
                            "page": page_ref + 1
                            })
                        
                        if not args["no_pdf"]:
                            # Add bookmark w/ parent, abandon as potential parent
                            temp = output_pdf.addBookmark(bm_name, page_ref, parent=bm_parent)
                    else:
                        # It's a file
                        page_index = page_list_files.index(filename)
                        last_page_index = page_index
        iterdict(page_dict, base_path=final_input_dir)
        print("\tDone!")
        
    if not args["no_pdf"]:
        print("Saving bookmarked PDF: {}".format(output_file))
        
        # Create PDF metadata
        pdf_metadata_dict = dict()
        if use_pdf_title:
            pdf_metadata_dict['/Title'] = pdf_title
        
        pdf_metadata_dict['/Author'] = pdf_author
        
        pdf_metadata_dict['/Producer'] = PROG_FILE_NAME
        
        # Add metadata to PDF
        output_pdf.addMetadata(pdf_metadata_dict)
        
        # Save final PDF
        with open(output_file, 'wb') as f:
            output_pdf.write(f)
        
        print("\tDone!")
    
    
    
    print()
    print("-------- TABLE OF CONTENTS --------")
    print("Building Table of Contents from bookmark hierarchy...")
    
    # Make row of ToC function
    def make_toc_row(bm_dict_in):
        ident = "".join([ident_str for x in range(bm_dict_in["level"])])
        page_toc_prefix = pagenum_pre + str(bm_dict_in["page"]).ljust(num_pages_len) + pagenum_post
        page_toc_base = page_toc_prefix + ident
        
        final_row = ""
        # Break name into multiple lines if it's too long
        if toc_line_break_limit != None:
            if len(bm_dict_in["name"]) > toc_line_break_limit:
                nm_lines = textwrap.fill(bm_dict_in["name"], width=toc_line_break_limit, break_long_words=False).split("\n")
                final_row += page_toc_base + nm_lines[0]
                for l in nm_lines[1:]:
                    base_space = "".join([" " for x in range(len(page_toc_base))])
                    final_row += "\n" + base_space + l
                return final_row
            
        # If we didn't break it up, just return it
        final_row += page_toc_base + bm_dict_in["name"]
        return final_row
    
    # Make rows of ToC
    toc_row_list = [make_toc_row(r) for r in toc_dict_list]
    
    # Get max line width
    toc_header_width = max([max([len(y) for y in x.split("\n")]) for x in toc_row_list])
    
    # Get ToC title
    toc_title_lines = textwrap.fill(pdf_title, width=toc_header_width, break_long_words=False).split("\n")
    toc_title = ["\n".join([x.center(toc_header_width) for x in toc_title_lines])]
    
    # Get ToC author (if applicable)
    toc_author = list()
    if len(pdf_author) > 0:
        toc_header_author = "by " + pdf_author
        toc_author_lines = textwrap.fill(toc_header_author, width=toc_header_width, break_long_words=False).split("\n")
        toc_author = ["\n".join([x.center(toc_header_width) for x in toc_author_lines])]
    
    # Get ToC label
    toc_label_lines = textwrap.fill("Table of Contents", width=toc_header_width, break_long_words=False).split("\n")
    toc_label = ["\n".join([x.center(toc_header_width) for x in toc_label_lines])]
    
    # Get ToC seperator
    toc_sep = ["".join(["-" for x in range(toc_header_width)])]
    
    # Get page count text
    toc_pagecount = ["\tPage count: {}".format(num_pages)]
    
    # Make list with all ToC lines
    final_toc_list = toc_title + toc_author + toc_label + toc_sep + toc_row_list + toc_pagecount
    
    print("\tDone!")
    
    # Print ToC lines
    print()
    for r in final_toc_list:
        print(r)
    
    
        
    # Set to print after other exit tasks
    def job_complete():
        print()
        print("-------- JOB COMPLETE --------")
        print("Page count: {}".format(num_pages))
        if not args["no_pdf"]:
            print("Final PDF location: {}".format(output_file))
            print("File size: {} bytes".format(os.path.getsize(output_file)))
except KeyboardInterrupt:
    print()
    print()
    print()
    print("[CTRL-C] Exiting...")