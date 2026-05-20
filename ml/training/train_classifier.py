"""
lighting-ai/ml/training/train_classifier.py

Trains the zone classifier.  Three data sources (combinable):
  --synthetic        300 samples/class from hand-crafted profiles (bootstrap)
  --from-reference   Extract features from the real Rossmann EG reference plan
  --annotations PATH Load JSONL file {"features":{…}, "zone_type":"sales_floor"}

RL loop: corrections written by the API (JSON files in data/annotations/)
are loaded automatically and mixed into the training set.

Usage:
  python ml/training/train_classifier.py --synthetic
  python ml/training/train_classifier.py --from-reference --synthetic
  python ml/training/train_classifier.py --annotations data/annotations/labels.jsonl
"""
from __future__ import annotations
import argparse, json, pickle, random, sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score, StratifiedKFold, train_test_split
from sklearn.metrics import classification_report

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import MODELS_DIR, ANNOTATIONS_DIR

FEATURE_KEYS = [
    "area_m2","width_m","height_m","aspect_ratio","perimeter_m",
    "ceiling_h_m","n_checkout","n_shelving","n_desk","n_storage",
    "n_door","n_window","total_furniture","shelving_density",
]

def _r(a,b):  return random.uniform(a,b)
def _ri(a,b): return random.randint(a,b)

PROFILES = {
    "sales_floor":    lambda: {"area_m2":_r(200,700),"width_m":_r(10,30),"height_m":_r(15,45),
        "aspect_ratio":_r(1.5,4.0),"perimeter_m":_r(60,160),"ceiling_h_m":_r(3.0,4.5),
        "n_checkout":0,"n_shelving":_ri(30,200),"n_desk":0,"n_storage":0,
        "n_door":_ri(1,4),"n_window":_ri(0,6),"n_unknown":0,
        "total_furniture":_ri(30,200),"shelving_density":_r(0.05,0.30)},
    "checkout_zone":  lambda: {"area_m2":_r(5,60),"width_m":_r(3,10),"height_m":_r(2,8),
        "aspect_ratio":_r(1.2,3.5),"perimeter_m":_r(15,40),"ceiling_h_m":_r(2.8,3.5),
        "n_checkout":_ri(1,8),"n_shelving":_ri(0,3),"n_desk":0,"n_storage":0,
        "n_door":0,"n_window":0,"n_unknown":0,"total_furniture":_ri(1,10),"shelving_density":0.0},
    "entrance":       lambda: {"area_m2":_r(3,25),"width_m":_r(2,6),"height_m":_r(2,5),
        "aspect_ratio":_r(1.0,2.5),"perimeter_m":_r(12,30),"ceiling_h_m":_r(3.0,5.0),
        "n_checkout":0,"n_shelving":_ri(0,2),"n_desk":0,"n_storage":0,
        "n_door":_ri(1,3),"n_window":_ri(2,8),"n_unknown":0,
        "total_furniture":_ri(0,5),"shelving_density":0.0},
    "storage":        lambda: {"area_m2":_r(5,100),"width_m":_r(3,12),"height_m":_r(2,10),
        "aspect_ratio":_r(1.0,3.0),"perimeter_m":_r(14,50),"ceiling_h_m":_r(2.8,4.5),
        "n_checkout":0,"n_shelving":_ri(0,5),"n_desk":0,"n_storage":_ri(1,10),
        "n_door":_ri(0,2),"n_window":0,"n_unknown":_ri(0,3),
        "total_furniture":_ri(1,12),"shelving_density":_r(0.0,0.08)},
    "office":         lambda: {"area_m2":_r(8,60),"width_m":_r(3,8),"height_m":_r(3,8),
        "aspect_ratio":_r(1.0,2.5),"perimeter_m":_r(18,36),"ceiling_h_m":_r(2.7,3.2),
        "n_checkout":0,"n_shelving":_ri(0,2),"n_desk":_ri(2,8),"n_storage":_ri(0,2),
        "n_door":_ri(1,2),"n_window":_ri(0,4),"n_unknown":_ri(0,2),
        "total_furniture":_ri(2,12),"shelving_density":0.0},
    "corridor":       lambda: {"area_m2":_r(5,50),"width_m":_r(1.5,3.5),"height_m":_r(5,20),
        "aspect_ratio":_r(4.0,12.0),"perimeter_m":_r(14,50),"ceiling_h_m":_r(2.8,3.2),
        "n_checkout":0,"n_shelving":0,"n_desk":0,"n_storage":0,
        "n_door":_ri(0,3),"n_window":0,"n_unknown":0,
        "total_furniture":_ri(0,3),"shelving_density":0.0},
    "service_area":   lambda: {"area_m2":_r(3,30),"width_m":_r(2,6),"height_m":_r(2,6),
        "aspect_ratio":_r(1.0,2.5),"perimeter_m":_r(12,28),"ceiling_h_m":_r(2.7,3.2),
        "n_checkout":0,"n_shelving":_ri(0,2),"n_desk":_ri(0,2),"n_storage":_ri(0,2),
        "n_door":_ri(0,2),"n_window":_ri(0,2),"n_unknown":0,
        "total_furniture":_ri(0,5),"shelving_density":0.0},
}

def _fvec(feat): return np.array([feat.get(k,0.0) for k in FEATURE_KEYS],dtype=np.float32)

def generate_synthetic(n_per_class=300):
    X,y=[],[]
    for zt,gen in PROFILES.items():
        for _ in range(n_per_class): X.append(_fvec(gen())); y.append(zt)
    idx=np.random.permutation(len(X))
    return np.array(X)[idx],[y[i] for i in idx]

def load_annotations(path):
    X,y=[],[]
    with open(path) as f:
        for line in f:
            line=line.strip()
            if not line: continue
            obj=json.loads(line); X.append(_fvec(obj["features"])); y.append(obj["zone_type"])
    print(f"Loaded {len(X)} annotations from {path}"); return np.array(X),y

def extract_from_reference(output_jsonl=None):
    """Extract zone features from the real Rossmann EG plan as training samples."""
    from shapely.geometry import Point
    ref=Path("/mnt/user-data/uploads/3600_HH_Jungfernstieg_EG_SB_Kassen_20240506.pdf")
    if not ref.exists():
        print("Reference plan not found, skipping."); return np.empty((0,len(FEATURE_KEYS))),[]
    from services.parser.pdf_parser import RealPlanParser
    from services.classifier.room_classifier_real import RealRoomClassifier
    plan=RealPlanParser().parse(ref)
    clf=RealRoomClassifier().classify(plan)
    samples=[]
    for zone in clf.zones:
        b=zone.polygon.bounds; w=(b[2]-b[0])/1000; h=(b[3]-b[1])/1000
        fi=[f for f in plan.furniture if zone.polygon.contains(Point(f.position))]
        feat={"area_m2":zone.area_m2,"width_m":w,"height_m":h,
              "aspect_ratio":max(w,h)/max(min(w,h),0.1),
              "perimeter_m":zone.polygon.length/1000,
              "ceiling_h_m":zone.ceiling_height_mm/1000,
              "n_checkout":zone.furniture_counts.get("checkout",0),
              "n_shelving":zone.furniture_counts.get("shelving",0),
              "n_desk":0,"n_storage":0,"n_door":0,"n_window":0,"n_unknown":0,
              "total_furniture":sum(zone.furniture_counts.values()),
              "shelving_density":zone.furniture_counts.get("shelving",0)/max(zone.area_m2,1)}
        samples.append({"features":feat,"zone_type":zone.zone_type})
    if output_jsonl:
        Path(output_jsonl).parent.mkdir(parents=True,exist_ok=True)
        with open(output_jsonl,'w') as f:
            for s in samples: f.write(json.dumps(s)+"\n")
        print(f"Saved {len(samples)} real samples → {output_jsonl}")
    X=np.array([_fvec(s["features"]) for s in samples])
    return X,[s["zone_type"] for s in samples]

def load_corrections(corrections_dir):
    """Load designer correction JSON files for RL retraining signal."""
    d=Path(corrections_dir)
    if not d.exists(): return np.empty((0,len(FEATURE_KEYS))),[]
    X,y=[],[]
    for jf in d.glob("*_corrections.json"):
        for c in json.loads(jf.read_text()):
            zt=c.get("zone_type","unknown")
            if zt!="unknown": X.append(_fvec({k:0.0 for k in FEATURE_KEYS})); y.append(zt)
    print(f"Loaded {len(X)} correction samples from {corrections_dir}"); return np.array(X) if X else np.empty((0,len(FEATURE_KEYS))),y

def train(X,y,save=True):
    from collections import Counter
    print(f"\nTraining: {len(X)} samples, classes: {dict(Counter(y))}")
    clf=RandomForestClassifier(n_estimators=400,max_depth=14,min_samples_leaf=2,
        max_features="sqrt",class_weight="balanced",random_state=42,n_jobs=-1)
    n_splits=min(5,min(Counter(y).values())) if len(set(y))>1 and len(X)>=10 else 2
    if len(X)>=10 and len(set(y))>=2:
        cv=StratifiedKFold(n_splits=n_splits,shuffle=True,random_state=42)
        scores=cross_val_score(clf,X,y,cv=cv,scoring="f1_macro")
        print(f"  CV F1-macro: {scores.mean():.3f} ± {scores.std():.3f}")
    clf.fit(X,y)
    if len(X)>=20 and len(set(y))>=2:
        Xtr,Xte,ytr,yte=train_test_split(X,y,test_size=0.2,stratify=y,random_state=99)
        e=RandomForestClassifier(n_estimators=400,max_depth=14,min_samples_leaf=2,
            class_weight="balanced",random_state=42,n_jobs=-1)
        e.fit(Xtr,ytr); print("\nHold-out report:\n"+classification_report(yte,e.predict(Xte)))
    if save:
        MODELS_DIR.mkdir(parents=True,exist_ok=True)
        mp=MODELS_DIR/"room_classifier.pkl"
        with open(mp,"wb") as f: pickle.dump(clf,f)
        print(f"Model saved → {mp}")
    return clf

def feat_importance(clf):
    ranked=sorted(zip(FEATURE_KEYS,clf.feature_importances_),key=lambda x:x[1],reverse=True)
    print("\nFeature importances:")
    for feat,imp in ranked:
        print(f"  {feat:<24} {imp:.4f}  {'█'*int(imp*50)}")

if __name__=="__main__":
    ap=argparse.ArgumentParser(description="Train zone classifier")
    ap.add_argument("--synthetic",action="store_true")
    ap.add_argument("--from-reference",action="store_true")
    ap.add_argument("--annotations",default=None)
    ap.add_argument("--corrections",default=None)
    ap.add_argument("--n-per-class",type=int,default=300)
    ap.add_argument("--no-save",action="store_true")
    args=ap.parse_args()

    X_all=np.empty((0,len(FEATURE_KEYS)),dtype=np.float32); y_all=[]

    if args.from_reference:
        labels_out=str(ANNOTATIONS_DIR/"labels.jsonl")
        Xr,yr=extract_from_reference(output_jsonl=labels_out)
        if len(Xr): X_all=np.vstack([X_all,Xr]) if len(X_all) else Xr; y_all.extend(yr)

    if args.annotations and Path(args.annotations).exists():
        Xa,ya=load_annotations(args.annotations)
        if len(Xa): X_all=np.vstack([X_all,Xa]) if len(X_all) else Xa; y_all.extend(ya)

    if args.corrections:
        Xc,yc=load_corrections(args.corrections)
        if len(Xc): X_all=np.vstack([X_all,Xc]) if len(X_all) else Xc; y_all.extend(yc)

    if args.synthetic or len(X_all)<50:
        print(f"Generating {args.n_per_class} synthetic samples/class …")
        Xs,ys=generate_synthetic(args.n_per_class)
        X_all=np.vstack([X_all,Xs]) if len(X_all) else Xs; y_all.extend(ys)

    if len(X_all)==0: print("No training data. Use --synthetic."); sys.exit(1)
    clf=train(X_all,y_all,save=not args.no_save)
    feat_importance(clf)
    print(f"\nDone. {len(X_all)} samples total.")