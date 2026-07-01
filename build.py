import json
import os

def build_dashboard():
    """
    Reads the source HTML and map data, injects the data into the HTML,
    and writes a final, self-contained distribution file.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_html_path = os.path.join(base_dir, 'index.html')
    map_data_path = os.path.join(base_dir, 'eve_map_data.json')
    output_html_path = os.path.join(base_dir, 'EVE_Intel_Dashboard.html')
    placeholder = 'MAP_DATA_PLACEHOLDER'

    try:
        print("Reading source files...")
        with open(template_html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        with open(map_data_path, 'r', encoding='utf-8') as f:
            json_content = f.read()

        print(f"Injecting map data and writing to '{output_html_path}'...")
        final_html = html_content.replace(placeholder, json_content)
        with open(output_html_path, 'w', encoding='utf-8') as f:
            f.write(final_html)

        print("\nBuild successful!")
        print(f"'{output_html_path}' is ready for distribution.")

    except FileNotFoundError as e:
        print(f"\n[ERROR] Build failed. Could not find a required file: {e.filename}")
    except Exception as e:
        print(f"\n[ERROR] An unexpected error occurred during the build process: {e}")

if __name__ == "__main__":
    build_dashboard()