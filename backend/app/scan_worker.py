def execute_scan(parameters, progress):
    # Import in the child so market-data state is isolated from web requests.
    from .main import scan, scan_all
    if parameters['mode'] == 'all':
        return scan_all(parameters['index'], parameters['direction'], progress_callback=progress)
    return scan(parameters['index'], parameters['setup'], parameters['near_matches'],
                parameters['near_match_score'], progress_callback=progress)
