"""Produce a PRIVATE no-model replan preview; never connect to a live database."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline.memory_center.replan import preview


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--conversations',required=True)
    parser.add_argument('--previous-metadata',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];target=Path(args.output).resolve()
    if target==root or root in target.parents:raise ValueError('Private preview output must be outside the repository')
    source=Path(args.conversations);old=Path(args.previous_metadata)
    result=preview(json.loads(source.read_text()),json.loads(old.read_text()))
    result['archive_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Exclusive creation: do not overwrite a prior preview receipt.
    with target.open('x') as file:
        target.chmod(0o600);json.dump(result,file,ensure_ascii=False,indent=2)
    print(json.dumps({'parser_version':result['parser_version'],'policy':result['policy'],'summary':result['summary']},ensure_ascii=False))


if __name__=='__main__':main()
