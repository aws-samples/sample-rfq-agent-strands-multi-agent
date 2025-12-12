import boto3
import time

def run_glue_crawlers(crawler_names, wait_for_completion=True):
    """
    Run Glue crawlers and optionally wait for completion
    """
    glue = boto3.client('glue')
    
    for crawler_name in crawler_names:
        print(f"Starting crawler: {crawler_name}")
        try:
            glue.start_crawler(Name=crawler_name)
            print(f"  ✓ Crawler {crawler_name} started")
        except glue.exceptions.CrawlerRunningException:
            print(f"  ⚠ Crawler {crawler_name} already running")
        except Exception as e:
            print(f"  ✗ Error starting {crawler_name}: {e}")
            continue
    
    if wait_for_completion:
        print("\nWaiting for crawlers to complete...")
        for crawler_name in crawler_names:
            while True:
                response = glue.get_crawler(Name=crawler_name)
                state = response['Crawler']['State']
                
                if state == 'READY':
                    print(f"  ✓ {crawler_name} completed")
                    break
                elif state in ['RUNNING', 'STOPPING']:
                    print(f"  ⏳ {crawler_name} is {state.lower()}...")
                    time.sleep(10)
                else:
                    print(f"  ⚠ {crawler_name} state: {state}")
                    break

if __name__ == '__main__':
    # Update with your crawler names from CloudFormation outputs
    crawlers = [
        'ChatApp-sap-data-crawler',
        'ChatApp-comp-data-crawler'
    ]
    
    run_glue_crawlers(crawlers, wait_for_completion=True)
    print("\n✓ All crawlers completed!")
