


proof(List,Value,Type):-
    re_order(List,[P1,P2,Conclusion]),
    check_syll(P1,P2,Conclusion,Value,Type).

proof(_,error,error).  % wenn keine 3er Liste von Tripeln

    
check_syll(P1,P2,Conclusion,Value,Type):-
   syllogism([P1,P2], Conclusion, Value,Type),!.

check_syll(P1,P2,Conclusion,Value,Type):-
   syllogism([P2,P1], Conclusion, Value,Type),!.

check_syll(_,_,_,false,unknown). % Wenn kein Syllogismus passt


re_order([],[]).
re_order([(A,B,C)|T],[(C,A,B)|T1]):-
   re_order(T,T1).


% Syllogismen

% --- 1. FIGUR (M ist Prädikat in P1, Subjekt in P2) ---

% Barbara: Alle M sind A, Alle B sind M -> Alle B sind A.
syllogism([(A,a,M), (M,a,B)], (A,a,B), true, barbara).

% Celarent: Kein M ist A, Alle B sind M -> Kein B ist A.
syllogism([(A,e,M), (M,a,B)], (A,e,B), true, celarent).

% Darii: Alle M sind A, Einige B sind M -> Einige B sind A.
syllogism([(A,a,M), (M,i,B)], (A,i,B), true, darii).

% Ferio: Kein M ist A, Einige B sind M -> Einige B sind nicht A.
syllogism([(A,e,M), (M,i,B)], (A,o,B), true, ferio).

% --- 2. FIGUR (M ist Prädikat in beiden Prämissen) ---

% Cesare: Kein A ist M, Alle B sind M -> Kein B ist A.
syllogism([(M,e,A), (M,a,B)], (A,e,B), true, cesare).

% Camestres: Alle A sind M, Kein B ist M -> Kein B ist A.
syllogism([(M,a,A), (M,e,B)], (A,e,B), true, camestres).

% Festino: Kein A ist M, Einige B sind M -> Einige B sind nicht A.
syllogism([(M,e,A), (M,i,B)], (A,o,B), true, festino).

% Baroco: Alle A sind M, Einige B sind nicht M -> Einige B sind nicht A.
syllogism([(M,a,A), (M,o,B)], (A,o,B), true, baroco).

% --- 3. FIGUR (M ist Subjekt in beiden Prämissen) ---

% Darapti: Alle M sind A, Alle M sind B -> Einige B sind A.
syllogism([(A,a,M), (B,a,M)], (A,i,B), true, darapti).

% Disamis: Einige M sind A, Alle M sind B -> Einige B sind A.
syllogism([(A,i,M), (B,a,M)], (A,i,B), true, disamis).

% Datisi: Alle M sind A, Einige M sind B -> Einige B sind A.
syllogism([(A,a,M), (B,i,M)], (A,i,B), true, datisi).

% Felapton: Kein M ist A, Alle M sind B -> Einige B sind nicht A.
syllogism([(A,e,M), (B,a,M)], (A,o,B), true, felapton).

% Bocardo: Einige M sind nicht A, Alle M sind B -> Einige B sind nicht A.
syllogism([(A,o,M), (B,a,M)], (A,o,B), true, bocardo).

% Ferison: Kein M ist A, Einige M sind B -> Einige B sind nicht A.
syllogism([(A,e,M), (B,i,M)], (A,o,B), true, ferison).


% --- 4. FIGUR (M ist erst Prädikat und dann Subjekt in den Prämissen) ---
% Bramantip: Alle A sind M, Alle M sind B -> Einige B sind A.
syllogism([(M,a,A), (B,a,M)], (A,i,B), true, bramantip).

% Camenes: Alle A sind M, Kein M ist B -> Kein B ist A.
syllogism([(M,a,A), (B,e,M)], (A,e,B), true, camenes).

% Dimaris: Einige A sind M, Alle M sind B -> Einige B sind A.
syllogism([(M,i,A), (B,a,M)], (A,i,B), true, dimaris).

% Fesapo: Kein A ist M, Alle M sind B -> Einige B sind nicht A.
syllogism([(M,e,A), (B,a,M)], (A,o,B), true, fesapo).

% Fresison: Kein A ist M, Einige M sind B -> Einige B sind nicht A.
syllogism([(M,e,A), (B,i,M)], (A,o,B), true, fresison).



% subalterne Modi
% 1. Figur
% Barbari: Alle M sind A, Alle B sind M -> Einige B sind A.
syllogism([(A,a,M), (M,a,B)], (A,i,B), true, barbari).

% Celaront: Kein M ist A, Alle B sind M -> Einige B sind nicht A.
syllogism([(A,e,M), (M,a,B)], (A,o,B), true, celaront).

% 2. Figur
% Cesaro: Kein A ist M, Alle B sind M -> Einige B sind nicht A.
syllogism([(M,e,A), (M,a,B)], (A,o,B), true, cesaro).

% Camestros: Alle A sind M, Kein B ist M -> Einige B sind nicht A.
syllogism([(M,a,A), (M,e,B)], (A,o,B), true, camestros).

% 4. Figur
% Camenop: Alle A sind M, Kein M ist B -> Einige B sind nicht A.
syllogism([(M,a,A), (B,e,M)], (A,o,B), true, camenop).

